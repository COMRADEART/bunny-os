# Bunny OS interactive bootc payload. Image-builder supplies the offline source.
# There is intentionally no clearpart/autopart, user password, network credential,
# repository URL, or post-install shell command in this interactive default.
graphical
eula --agreed
firstboot --enable
firewall --enabled
selinux --enforcing
