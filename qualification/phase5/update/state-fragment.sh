# Sourced by stage.sh before the switch. Writes the state a rollback must not
# lose, and one thing it is *expected* to lose, so the result says something.
#
# §20: "A rollback that boots but loses user state is not automatically a PASS."
# A rollback test that only checks the machine boots has not tested that
# sentence, so state is written here, before the switch, and read back on every
# boot afterwards by bunny-p5-state.service.
#
# Two classes on purpose:
#
#   /var/...      the stateroot's /var is shared by every deployment, so this
#                 is what user data, settings and Trust records live in and
#                 what a rollback must preserve.
#   <deploy>/etc  per-deployment. A rollback goes back to the *previous*
#                 deployment's /etc, so a change made here after the switch is
#                 expected to disappear. Recording that is what makes the /var
#                 result mean something rather than being a tautology.
write_state() {
  say "writing pre-switch state"
  mkdir -p /var/home /var/lib/bunny-os/companion /var/lib/bunny-os/trust \
           /var/lib/bunny-os/voice /var/log/bunny-p5
  printf 'user data written before the switch at %s\n' "$(date -Is)" \
    >/var/home/p5-user-data.txt
  printf '{"mode":"attentive","setBy":"phase5 rollback qualification"}\n' \
    >/var/lib/bunny-os/companion/p5-mode.json
  printf '{"grants":[{"capsule":"p5-example","decision":"allow"}]}\n' \
    >/var/lib/bunny-os/trust/p5-grants.json
  printf '{"inputDevice":"p5-null-sink","volume":42}\n' \
    >/var/lib/bunny-os/voice/p5-settings.json
  printf 'settings written before the switch\n' \
    >/var/lib/bunny-os/p5-settings.txt
  sync
  say "state written:"
  run find /var/home/p5-user-data.txt /var/lib/bunny-os -name 'p5-*' -type f

  # The control: per-deployment, expected NOT to survive a rollback.
  printf 'etc marker written before the switch\n' >/etc/bunny-p5-etc-marker.txt
  say "control marker written to /etc (per-deployment, expected to be lost on rollback)"
}
