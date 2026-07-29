# Update trust material

This directory intentionally contains no private key and no release public key. Pull-request and developer builds ship with OS updates disabled. Release engineering injects reviewed Ed25519 public keys into the image build context and keeps signing keys offline or in a protected signing service.

Key rotation overlaps two public keys. `revoked-keys.json` is itself distributed through the signed image and rejects named key IDs. Channel manifests and image repositories are isolated by configuration.

