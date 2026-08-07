# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The renderer's own GLSL. A character package can never contribute a line.

§19 permits exactly this: a small fixed material model, glTF metallic-roughness,
fixed shader variants, alpha, skinning and morph targets — compiled from source
that lives in this repository and is selected by a *variant flag*, never
concatenated from anything a package supplied. There is no path from manifest
text to a shader string, and ``tests/companion/test_three_d_security.py`` asserts
that the only strings ever handed to ``glShaderSource`` come from this module.

The two numbers that are substituted — the joint-array size and the number of
simultaneously active morph targets — are integers this renderer computed from
an already-validated model, clamped to what the driver reported. They are
formatted with ``%d`` into a ``#define``; a package cannot reach them, and a
model that needs more joints than the driver's uniform budget allows is refused
with a typed capability error rather than compiled into something that links and
draws the wrong skeleton.

Morph targets arrive as an ``RGB32F`` texture rather than as vertex attributes:
GL 3.3 core guarantees sixteen vertex attributes, six of which the base mesh
already uses, and a twenty-four-target face would need seventy-two. One texture
fetch per *active* target — at most :data:`MAX_ACTIVE_MORPHS`, chosen on the CPU
by weight — costs a bounded amount whatever the package declares.
"""

from __future__ import annotations

from typing import Any

#: How many morph targets may contribute to one frame. An expression plus a
#: viseme plus a blink is three; eight is generous and keeps the vertex shader's
#: inner loop short enough to matter on a software rasteriser.
MAX_ACTIVE_MORPHS = 8

#: The attribute locations, bound explicitly before linking so the renderer
#: never has to query them and a driver cannot reorder them.
ATTRIBUTE_LOCATIONS: dict[str, int] = {
    "aPosition": 0,
    "aNormal": 1,
    "aTexCoord": 2,
    "aJoints": 3,
    "aWeights": 4,
    "aColour": 5,
}

VERTEX_SHADER = """#version 330 core
#define MAX_JOINTS %(joints)d
#define MAX_ACTIVE_MORPHS %(morphs)d

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aTexCoord;
layout(location = 3) in vec4 aJoints;
layout(location = 4) in vec4 aWeights;
layout(location = 5) in vec4 aColour;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;
uniform mat4 uJoints[MAX_JOINTS];
uniform int  uSkinned;

uniform sampler2D uMorphTexture;
uniform int   uMorphActive;
uniform int   uMorphIndex[MAX_ACTIVE_MORPHS];
uniform float uMorphWeight[MAX_ACTIVE_MORPHS];
uniform int   uMorphTexWidth;
uniform int   uVertexCount;
uniform int   uMorphHasNormals;

out vec3 vWorldPosition;
out vec3 vNormal;
out vec2 vTexCoord;
out vec4 vColour;

vec3 morphDelta(int target, int component)
{
    int texel = (target * (uMorphHasNormals == 1 ? 2 : 1) + component) * uVertexCount + gl_VertexID;
    int row = texel / uMorphTexWidth;
    int column = texel - row * uMorphTexWidth;
    return texelFetch(uMorphTexture, ivec2(column, row), 0).rgb;
}

void main()
{
    vec3 position = aPosition;
    vec3 normal = aNormal;

    for (int i = 0; i < MAX_ACTIVE_MORPHS; ++i) {
        if (i >= uMorphActive) { break; }
        float weight = uMorphWeight[i];
        if (weight == 0.0) { continue; }
        int target = uMorphIndex[i];
        position += weight * morphDelta(target, 0);
        if (uMorphHasNormals == 1) {
            normal += weight * morphDelta(target, 1);
        }
    }

    mat4 skin = mat4(1.0);
    if (uSkinned == 1) {
        skin =
            aWeights.x * uJoints[int(aJoints.x)] +
            aWeights.y * uJoints[int(aJoints.y)] +
            aWeights.z * uJoints[int(aJoints.z)] +
            aWeights.w * uJoints[int(aJoints.w)];
        float total = aWeights.x + aWeights.y + aWeights.z + aWeights.w;
        if (total <= 0.0001) { skin = mat4(1.0); }
    }

    mat4 world = uModel * skin;
    vec4 worldPosition = world * vec4(position, 1.0);
    vWorldPosition = worldPosition.xyz;
    vNormal = normalize(mat3(world) * normal);
    vTexCoord = aTexCoord;
    vColour = aColour;
    gl_Position = uProjection * uView * worldPosition;
}
"""

FRAGMENT_SHADER = """#version 330 core
#define ALPHA_MODE %(alpha_mode)d
#define UNLIT %(unlit)d
#define LIGHTWEIGHT %(lightweight)d

in vec3 vWorldPosition;
in vec3 vNormal;
in vec2 vTexCoord;
in vec4 vColour;

uniform vec4  uBaseColour;
uniform float uMetallic;
uniform float uRoughness;
uniform vec3  uEmissive;
uniform int   uHasBaseTexture;
uniform sampler2D uBaseTexture;

uniform vec3  uKeyDirection;
uniform vec3  uKeyColour;
uniform float uKeyIntensity;
uniform vec3  uFillDirection;
uniform vec3  uFillColour;
uniform float uFillIntensity;
uniform vec3  uAmbient;
uniform vec3  uCameraPosition;
uniform float uAlphaCutoff;
uniform float uOpacity;

out vec4 fragment;

const float PI = 3.14159265359;

float distributionGGX(vec3 normal, vec3 halfway, float roughness)
{
    float a = roughness * roughness;
    float a2 = a * a;
    float ndoth = max(dot(normal, halfway), 0.0);
    float denominator = ndoth * ndoth * (a2 - 1.0) + 1.0;
    return a2 / max(PI * denominator * denominator, 1e-6);
}

float geometrySchlick(float ndotv, float roughness)
{
    float k = (roughness + 1.0) * (roughness + 1.0) / 8.0;
    return ndotv / max(ndotv * (1.0 - k) + k, 1e-6);
}

vec3 fresnelSchlick(float cosine, vec3 f0)
{
    return f0 + (1.0 - f0) * pow(clamp(1.0 - cosine, 0.0, 1.0), 5.0);
}

vec3 contribution(vec3 normal, vec3 view, vec3 lightDirection, vec3 lightColour,
                  float intensity, vec3 albedo, vec3 f0, float roughness, float metallic)
{
    vec3 light = normalize(-lightDirection);
    float ndotl = max(dot(normal, light), 0.0);
    if (ndotl <= 0.0) { return vec3(0.0); }
#if LIGHTWEIGHT == 1
    return albedo * lightColour * intensity * ndotl;
#else
    vec3 halfway = normalize(view + light);
    float ndotv = max(dot(normal, view), 1e-4);
    float distribution = distributionGGX(normal, halfway, roughness);
    float geometry = geometrySchlick(ndotv, roughness) * geometrySchlick(ndotl, roughness);
    vec3 fresnel = fresnelSchlick(max(dot(halfway, view), 0.0), f0);
    vec3 specular = (distribution * geometry * fresnel) / max(4.0 * ndotv * ndotl, 1e-4);
    vec3 diffuse = (vec3(1.0) - fresnel) * (1.0 - metallic) * albedo / PI;
    return (diffuse + specular) * lightColour * intensity * ndotl;
#endif
}

void main()
{
    vec4 base = uBaseColour * vColour;
    if (uHasBaseTexture == 1) {
        base *= texture(uBaseTexture, vTexCoord);
    }

#if ALPHA_MODE == 1
    if (base.a < uAlphaCutoff) { discard; }
#endif

#if UNLIT == 1
    vec3 colour = base.rgb;
#else
    vec3 normal = normalize(vNormal);
    vec3 view = normalize(uCameraPosition - vWorldPosition);
    if (!gl_FrontFacing) { normal = -normal; }
    float roughness = clamp(uRoughness, 0.045, 1.0);
    vec3 f0 = mix(vec3(0.04), base.rgb, uMetallic);
    vec3 colour = uAmbient * base.rgb;
    colour += contribution(normal, view, uKeyDirection, uKeyColour, uKeyIntensity,
                           base.rgb, f0, roughness, uMetallic);
#if LIGHTWEIGHT == 0
    colour += contribution(normal, view, uFillDirection, uFillColour, uFillIntensity,
                           base.rgb, f0, roughness, uMetallic);
#endif
    colour += uEmissive;
#endif

    colour = colour / (colour + vec3(1.0));
    colour = pow(colour, vec3(1.0 / 2.2));

    float alpha = base.a * uOpacity;
#if ALPHA_MODE == 0
    alpha = uOpacity;
#endif
    fragment = vec4(colour, alpha);
}
"""

#: Numeric alpha-mode codes used by the ``#define``. Kept here so the renderer
#: never formats a *string* from a package into shader source.
ALPHA_MODES: dict[str, int] = {"OPAQUE": 0, "MASK": 1, "BLEND": 2}


def shader_sources(
    *, joints: int, unlit: bool, alpha_mode: str, lightweight: bool
) -> tuple[str, str, dict[str, Any]]:
    """One variant's vertex and fragment source, plus the key that selects it.

    Every substituted value is an integer this module bounded. ``alpha_mode``
    is looked up in a closed table rather than interpolated, so a package that
    somehow reached this function with ``"OPAQUE; void main(){}"`` gets a
    :class:`KeyError` and no shader.
    """
    if not 1 <= int(joints) <= 256:
        raise ValueError("shader joint count is outside the supported range")
    alpha = ALPHA_MODES[str(alpha_mode)]
    substitutions = {
        "joints": int(joints),
        "morphs": MAX_ACTIVE_MORPHS,
        "alpha_mode": alpha,
        "unlit": 1 if unlit else 0,
        "lightweight": 1 if lightweight else 0,
    }
    key = {
        "joints": substitutions["joints"],
        "alphaMode": str(alpha_mode),
        "unlit": bool(unlit),
        "lightweight": bool(lightweight),
    }
    return VERTEX_SHADER % substitutions, FRAGMENT_SHADER % substitutions, key


__all__ = [
    "ALPHA_MODES",
    "ATTRIBUTE_LOCATIONS",
    "FRAGMENT_SHADER",
    "MAX_ACTIVE_MORPHS",
    "VERTEX_SHADER",
    "shader_sources",
]
