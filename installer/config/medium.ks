# The payload directive for this medium, and the only thing the setup
# backend takes from this file: the rendered kickstart's payload directive is
# extracted from the medium, never composed by code.
#
# The OCI layout it names is exported from the exact payload image this
# medium was built beside, and rides in the live filesystem so the path
# exists whether the medium is a disc, a USB stick, or a qcow2 in a harness.
# Signature verification is off because the layout is local and unsigned;
# the medium itself is the trust boundary, covered by its ISO digest and the
# Secure Boot chain that booted it.
ostreecontainer --url=/usr/share/bunny-os/payload-oci --transport=oci --no-signature-verification
