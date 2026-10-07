# Application-only policy for the reference transit/gateway key.
# Provision/rotate the key with a separate operator identity.
path "transit/keys/gateway" {
  capabilities = ["read"]
}

path "transit/encrypt/gateway" {
  capabilities = ["update"]
}

path "transit/decrypt/gateway" {
  capabilities = ["update"]
}
