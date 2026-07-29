# Update compatibility

The normative matrix is `operations/data/update-compatibility.json`. An update is permitted only for one exact source/target entry with `directUpdateSupported=true` and a qualified rollback status. Unknown or duplicated routes are rejected. An intermediate release, schema/config migration, recovery requirement, rollback status, downgrade status, and limitations are displayed before staging.

Both placeholder beta-to-`stable-rc1` routes are disabled because no signed beta images, migration fixture, recovery media, or rollback execution exists. This is a deliberate `NO-GO`, not a user-facing update promise.
