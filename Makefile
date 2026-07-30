PYTHON ?= python3

.PHONY: audit installer-audit installer-schema phase5-audit phase-5-baseline import-beta-feedback triage-report release-dashboard validate test test-security test-broker test-shell test-launcher test-search test-workspace test-panel test-notifications test-approvals test-settings test-terminal test-accessibility test-performance test-desktop-security test-installer test-storage test-encryption test-dual-boot test-first-run test-app-distribution test-installer-security test-phase5 test-update-security test-rollbacks test-recovery test-migrations test-hardware-report test-diagnostics test-redaction test-crash-reporting test-network-privacy test-application-catalogue test-release-signing test-installer-regressions test-update-regressions test-multi-user test-bunny-disabled test-local-only test-privacy-regressions test-accessibility-regressions test-hardware-matrix long-run-tests installer-performance build-developer-image build-shell-image build-shell-test-image build-live-image build-beta-image build-recovery-image build-stable-rc sign-stable-rc verify-stable-rc stable-artifacts inspect-image inspect-shell-image verify-install-media vm-smoke vm-shell-smoke vm-install-smoke vm-encrypted-install vm-upgrade-test vm-rollback-test vm-recovery-test reproducible-build-check sbom shell-sbom security-scan shell-security-scan license-scan shell-license-scan malware-scan performance-baseline gate gate-phase-2 gate-phase-3 gate-phase-4 gate-public-beta gate-phase-5 gate-stable-candidate gate-stable-release phase7-audit phase-7-baseline test-oem test-factory test-device-identity test-enrolment test-policy test-fleet test-multitenancy test-sync test-sync-crypto test-device-revocation test-remote-wipe test-airgap test-kiosk test-decommission test-pilot fleet-simulation pilot-readiness build-oem-image gate-phase-7-source gate-phase-7 gate-oem-pilot gate-enterprise-pilot gate-sync-pilot gate-dev-qualification dev-qualification-gaps qualification-compare release-blocker-baseline vulnerability-position reachability-review package-minimisation-check licence-gate independent-builder-prepare reproducibility-compare development-signing-drill signing-roles build-qualification-candidate build-independent-recovery validate-release-manifest test-installation-matrix test-encryption-matrix test-update-matrix test-rollback-matrix test-recovery-matrix test-preservation-matrix test-accessibility-matrix validate-hardware-evidence validate-independent-reviews stable-evidence-report pilot-closure-assertion test-release-closure

audit:
	$(PYTHON) scripts/task.py audit

installer-audit:
	$(PYTHON) scripts/task.py installer-audit

phase5-audit:
	$(PYTHON) scripts/task.py phase5-audit

phase-5-baseline:
	$(PYTHON) scripts/phase5.py baseline

import-beta-feedback:
	@test -n "$${FEEDBACK_EXPORT:-}" || { echo "set FEEDBACK_EXPORT to a structured local export" >&2; exit 1; }
	$(PYTHON) scripts/phase5.py import-feedback --source "$${FEEDBACK_EXPORT}" --output build/out/phase5/issue-ledger.json

triage-report:
	$(PYTHON) scripts/phase5.py triage-report --ledger operations/data/issue-ledger.json --output build/out/phase5/triage-report.md

release-dashboard:
	$(PYTHON) scripts/phase5.py dashboard

installer-schema:
	$(PYTHON) scripts/task.py validate

validate:
	$(PYTHON) scripts/task.py validate

test:
	$(PYTHON) scripts/task.py test

test-security:
	$(PYTHON) scripts/task.py test-security

test-broker:
	$(PYTHON) scripts/task.py test-broker

test-shell:
	$(PYTHON) scripts/task.py test-shell

test-launcher:
	$(PYTHON) scripts/task.py test-launcher

test-search:
	$(PYTHON) scripts/task.py test-search

test-workspace:
	$(PYTHON) scripts/task.py test-workspace

test-panel:
	$(PYTHON) scripts/task.py test-panel

test-notifications:
	$(PYTHON) scripts/task.py test-notifications

test-approvals:
	$(PYTHON) scripts/task.py test-approvals

test-settings:
	$(PYTHON) scripts/task.py test-settings

test-terminal:
	$(PYTHON) scripts/task.py test-terminal

test-accessibility:
	$(PYTHON) scripts/task.py test-accessibility

test-performance:
	$(PYTHON) scripts/task.py test-performance

test-desktop-security:
	$(PYTHON) scripts/task.py test-desktop-security

test-installer:
	$(PYTHON) scripts/task.py test-installer

test-storage:
	$(PYTHON) scripts/task.py test-storage

test-encryption:
	$(PYTHON) scripts/task.py test-encryption

test-dual-boot:
	$(PYTHON) scripts/task.py test-dual-boot

test-first-run:
	$(PYTHON) scripts/task.py test-first-run

test-app-distribution:
	$(PYTHON) scripts/task.py test-app-distribution

test-installer-security:
	$(PYTHON) scripts/task.py test-installer-security

test-phase5:
	$(PYTHON) scripts/task.py test-phase5

test-update-security:
	$(PYTHON) scripts/task.py test-update-regressions

test-rollbacks:
	$(PYTHON) scripts/task.py test-rollbacks

test-recovery:
	$(PYTHON) scripts/task.py test-recovery-qualification

test-migrations:
	$(PYTHON) scripts/task.py test-migrations

test-hardware-report:
	$(PYTHON) scripts/task.py test-hardware-report

test-diagnostics:
	$(PYTHON) scripts/task.py test-diagnostics

test-redaction:
	$(PYTHON) scripts/task.py test-redaction

test-crash-reporting:
	$(PYTHON) scripts/task.py test-crash-reporting

test-network-privacy:
	$(PYTHON) scripts/task.py test-network-privacy

test-application-catalogue:
	$(PYTHON) scripts/task.py test-application-catalogue

test-release-signing:
	$(PYTHON) scripts/task.py test-release-signing

test-installer-regressions:
	$(PYTHON) scripts/task.py test-installer-regressions

test-update-regressions:
	$(PYTHON) scripts/task.py test-update-regressions

test-multi-user:
	$(PYTHON) scripts/task.py test-multi-user

test-bunny-disabled:
	$(PYTHON) scripts/task.py test-bunny-disabled

test-local-only:
	$(PYTHON) scripts/task.py test-local-only

test-privacy-regressions:
	$(PYTHON) scripts/task.py test-privacy-regressions

test-accessibility-regressions:
	$(PYTHON) scripts/task.py test-accessibility-regressions

test-hardware-matrix:
	$(PYTHON) scripts/task.py test-hardware-matrix

long-run-tests:
	$(PYTHON) scripts/phase5.py long-run-plan

installer-performance:
	$(PYTHON) scripts/installer-performance.py

build-developer-image:
	bash build/scripts/build-image.sh developer

build-shell-image:
	bash build/scripts/build-image.sh shell

build-shell-test-image:
	bash build/scripts/build-image.sh shell-test

build-live-image:
	bash build/scripts/build-live-image.sh

build-beta-image:
	bash build/scripts/build-beta-image.sh

build-recovery-image:
	bash build/scripts/build-image.sh recovery

inspect-image:
	bash build/scripts/inspect-image.sh developer

inspect-shell-image:
	bash build/scripts/inspect-image.sh shell

vm-smoke:
	bash build/scripts/vm-smoke.sh developer

vm-shell-smoke:
	bash build/scripts/vm-shell-smoke.sh

verify-install-media:
	bash build/scripts/verify-install-media.sh

vm-install-smoke:
	bash build/scripts/vm-install-smoke.sh

vm-encrypted-install:
	bash build/scripts/vm-encrypted-install.sh

vm-upgrade-test:
	bash build/scripts/vm-upgrade-test.sh

vm-rollback-test:
	bash build/scripts/vm-rollback-test.sh

vm-recovery-test:
	bash build/scripts/vm-recovery-test.sh

reproducible-build-check:
	bash build/scripts/build-image.sh developer
	@echo "a second independent builder output comparison is required; one build is not reproducibility evidence"
	@exit 1

build-stable-rc:
	bash build/scripts/build-stable-rc.sh

sign-stable-rc:
	bash build/scripts/sign-stable-rc.sh

verify-stable-rc:
	@test -n "$${BUNNY_STABLE_PUBLIC_KEY:-}" || { echo "set BUNNY_STABLE_PUBLIC_KEY" >&2; exit 1; }
	$(PYTHON) build/scripts/verify-stable-rc.py --candidate "$${BUNNY_STABLE_CANDIDATE_DIR:-build/out/stable-rc}" --public-key "$${BUNNY_STABLE_PUBLIC_KEY}"

stable-artifacts: build-stable-rc sign-stable-rc verify-stable-rc

malware-scan:
	@echo "malware scan BLOCKED: no candidate artifact or pinned scanner configuration" >&2
	@exit 1

sbom:
	bash build/scripts/sbom.sh developer

shell-sbom:
	bash build/scripts/sbom.sh shell

performance-baseline:
	$(PYTHON) scripts/performance-baseline.py

security-scan:
	bash build/scripts/security-scan.sh developer

shell-security-scan:
	bash build/scripts/security-scan.sh shell

license-scan:
	$(PYTHON) build/scripts/license-scan.py build/out/developer/sbom/bunny-os.spdx.json $(if $(filter 1,$(BUNNY_RELEASE_BUILD)),--release,)

shell-license-scan:
	$(PYTHON) build/scripts/license-scan.py build/out/shell/sbom/bunny-os.spdx.json $(if $(filter 1,$(BUNNY_RELEASE_BUILD)),--release,)

gate: audit validate test test-security test-broker
	@if [ "$${FULL_GATE:-0}" = "1" ]; then \
		$(MAKE) build-developer-image build-recovery-image inspect-image vm-smoke sbom security-scan license-scan; \
	else \
		echo "Static gate passed. Set FULL_GATE=1 on the Fedora/KVM image builder to run artifact gates."; \
	fi

gate-phase-2: audit validate test test-security test-broker test-shell test-launcher test-search test-workspace test-panel test-notifications test-approvals test-settings test-terminal test-accessibility test-performance test-desktop-security
	@if [ "$${FULL_GATE:-0}" = "1" ]; then \
		$(MAKE) build-developer-image build-shell-image build-shell-test-image build-recovery-image inspect-image inspect-shell-image vm-smoke vm-shell-smoke sbom shell-sbom security-scan shell-security-scan license-scan shell-license-scan; \
	else \
		echo "Phase 2 static gate passed. Set FULL_GATE=1 on the Fedora/KVM image builder for image, SBOM, and VM gates."; \
	fi

gate-phase-3: gate-phase-2 installer-audit installer-schema test-installer test-storage test-encryption test-dual-boot test-first-run test-app-distribution test-installer-security
	@if [ "$${FULL_GATE:-0}" = "1" ]; then \
		$(MAKE) build-beta-image build-live-image build-recovery-image inspect-image verify-install-media vm-install-smoke vm-encrypted-install vm-upgrade-test sbom security-scan license-scan; \
	else \
		echo "Phase 3 static gate passed. Set FULL_GATE=1 only on the disposable-disk Fedora/KVM builder for destructive and artifact gates."; \
	fi

gate-phase-4 gate-public-beta:
	$(PYTHON) scripts/phase5.py phase4-preflight

gate-phase-5: gate-phase-3 phase5-audit phase-5-baseline test-phase5 test-installer-regressions test-update-regressions test-rollbacks test-recovery test-migrations test-multi-user test-bunny-disabled test-local-only test-privacy-regressions test-accessibility-regressions test-hardware-matrix test-crash-reporting test-application-catalogue test-release-signing long-run-tests
	$(PYTHON) scripts/phase5.py source-gate
	@echo "Phase 5 source/operations gate passed. Stable qualification remains NO-GO until runtime evidence and approvals pass."

gate-stable-candidate: gate-phase-5
	$(PYTHON) scripts/phase5.py candidate-gate --manifest build/out/stable-rc/STABLE-CANDIDATE.json

gate-stable-release: gate-stable-candidate
	$(PYTHON) scripts/phase5.py stable-gate --evidence operations/data/stable-qualification.json
	$(PYTHON) scripts/release.py gate --kind stable-release

# --- Release blocker closure ---------------------------------------------------
# Every target below fails closed. A target that cannot find the evidence it
# needs prints what is missing and exits 2.

release-blocker-baseline:
	$(PYTHON) scripts/release.py baseline

vulnerability-position:
	$(PYTHON) scripts/release.py vulnerability-position

reachability-review:
	$(PYTHON) scripts/release.py reachability-review

package-minimisation-check:
	$(PYTHON) scripts/release.py package-minimisation-check

licence-gate:
	$(PYTHON) scripts/release.py licence-gate

# Emit the exact inputs a second builder must reproduce. Requires a
# digest-pinned BUNNY_BASE_IMAGE so both builders pin the same base.
independent-builder-prepare:
	@test -n "$${BUNNY_BUILDER_ID:-}" || { echo "set BUNNY_BUILDER_ID to name this builder" >&2; exit 1; }
	$(PYTHON) scripts/release.py independent-builder-prepare --builder "$${BUNNY_BUILDER_ID}"

reproducibility-compare:
	$(PYTHON) scripts/release.py reproducibility-compare

development-signing-drill:
	$(PYTHON) scripts/signing_drill.py \
	  --release-artifact "$${BUNNY_RELEASE_ARTIFACT:-build/out/beta/bunny-os.oci.tar}" \
	  --recovery-artifact "$${BUNNY_RECOVERY_ARTIFACT:-build/out/recovery/bunny-os.oci.tar}"
	$(PYTHON) scripts/release.py development-signing-drill

signing-roles:
	$(PYTHON) scripts/release.py signing-roles

# Candidate artifacts. Named stable-rc or qualification-candidate; never
# "stable", which only gate-stable-release can authorise.
build-qualification-candidate:
	@test "$${BUNNY_RELEASE_BUILD:-0}" = "1" || { echo "set BUNNY_RELEASE_BUILD=1 and a digest-pinned BUNNY_BASE_IMAGE" >&2; exit 1; }
	BUNNY_CANDIDATE_NAME=qualification-candidate bash build/scripts/build-stable-rc.sh
	$(PYTHON) scripts/release.py validate-release-manifest

build-independent-recovery:
	bash build/scripts/build-image.sh recovery
	bash build/scripts/verify-install-media.sh recovery

validate-release-manifest:
	$(PYTHON) scripts/release.py validate-release-manifest

test-installation-matrix:
	$(PYTHON) scripts/release.py test-matrix --name installation

test-encryption-matrix:
	$(PYTHON) scripts/release.py test-matrix --name encryption

test-update-matrix:
	$(PYTHON) scripts/release.py test-matrix --name update

test-rollback-matrix:
	$(PYTHON) scripts/release.py test-matrix --name rollback

test-recovery-matrix:
	$(PYTHON) scripts/release.py test-matrix --name recovery-media

test-preservation-matrix:
	$(PYTHON) scripts/release.py test-matrix --name preservation

test-accessibility-matrix:
	$(PYTHON) scripts/release.py test-matrix --name accessibility

validate-hardware-evidence:
	$(PYTHON) scripts/release.py validate-hardware-evidence

validate-independent-reviews:
	$(PYTHON) scripts/release.py validate-independent-reviews

stable-evidence-report:
	$(PYTHON) scripts/release.py stable-evidence-report

# CI backstop: a gate reporting GO without protected evidence is a defect.
pilot-closure-assertion:
	$(PYTHON) scripts/release.py pilot-closure-assertion

test-release-closure:
	$(PYTHON) scripts/task.py test-release-closure

# --- Development qualification track ------------------------------------------
# A second, clearly-labelled evidence track. It can reach GO on virtual,
# development-key evidence. gate-stable-release is untouched, stays strict, and
# is the only gate that authorises a release.

gate-dev-qualification:
	$(PYTHON) scripts/devqual.py gate

dev-qualification-gaps:
	$(PYTHON) scripts/devqual.py gaps

qualification-compare:
	$(PYTHON) scripts/devqual.py compare

# --- Phase 7: OEM, enterprise management, and optional encrypted sync ---------

phase7-audit:
	$(PYTHON) scripts/task.py phase7-audit

phase-7-baseline:
	$(PYTHON) scripts/phase7.py baseline

test-oem:
	$(PYTHON) scripts/task.py test-oem

test-factory:
	$(PYTHON) scripts/task.py test-factory

test-device-identity:
	$(PYTHON) scripts/task.py test-device-identity

test-enrolment:
	$(PYTHON) scripts/task.py test-enrolment

test-policy:
	$(PYTHON) scripts/task.py test-policy

test-fleet:
	$(PYTHON) scripts/task.py test-fleet

test-multitenancy:
	$(PYTHON) scripts/task.py test-multitenancy

test-sync:
	$(PYTHON) scripts/task.py test-sync

test-sync-crypto:
	$(PYTHON) scripts/task.py test-sync-crypto

test-device-revocation:
	$(PYTHON) scripts/task.py test-device-revocation

test-remote-wipe:
	$(PYTHON) scripts/task.py test-remote-wipe

test-airgap:
	$(PYTHON) scripts/task.py test-airgap

test-kiosk:
	$(PYTHON) scripts/task.py test-kiosk

test-decommission:
	$(PYTHON) scripts/task.py test-decommission

test-pilot:
	$(PYTHON) scripts/task.py test-pilot

fleet-simulation:
	$(PYTHON) scripts/phase7.py fleet-simulation --devices $${BUNNY_FLEET_DEVICES:-500}

pilot-readiness:
	$(PYTHON) scripts/phase7.py pilot-readiness

# Validates an OEM profile and its overlay. A real image build additionally needs
# the Fedora/KVM image-builder host, so this target validates inputs only and
# says so rather than implying an artifact was produced.
build-oem-image:
	$(PYTHON) oem/bin/bunny-oem --json validate-profile --profile $${BUNNY_OEM_PROFILE:-oem/profiles/example-validated-integrator.json}
	$(PYTHON) oem/bin/bunny-oem --json validate-overlay --overlay $${BUNNY_OEM_OVERLAY:-oem/overlays/example-nimbus-overlay.json}
	@if [ "$${FULL_GATE:-0}" = "1" ]; then \
		bash build/scripts/build-image.sh developer; \
	else \
		echo "OEM profile and overlay validated. No image was built: set FULL_GATE=1 on the Fedora/KVM image builder."; \
	fi

# The Phase 7 source gate runs on any development host. It never implies a pilot
# approval, and the pilot gates below stay blocked while stable release is NO-GO.
gate-phase-7-source: validate phase7-audit phase-7-baseline test-oem test-factory test-device-identity test-enrolment test-policy test-fleet test-multitenancy test-sync test-sync-crypto test-device-revocation test-remote-wipe test-airgap test-kiosk test-decommission test-pilot
	$(PYTHON) scripts/phase7.py source-gate
	@echo "Phase 7 source gate passed. This is not a pilot, OEM, enterprise, or hosted-sync approval."

# The full Phase 7 gate inherits the stable-release gate and therefore fails
# closed while STABLE_RELEASE_GO_NO_GO.md records NO-GO.
gate-phase-7: gate-phase-7-source gate-stable-release
	$(PYTHON) scripts/phase7.py pilot-readiness

gate-oem-pilot: gate-phase-7-source
	$(PYTHON) scripts/phase7.py pilot-gate --kind oem
	$(PYTHON) scripts/release.py gate --kind oem-pilot

gate-enterprise-pilot: gate-phase-7-source
	$(PYTHON) scripts/phase7.py pilot-gate --kind enterprise
	$(PYTHON) scripts/release.py gate --kind enterprise-pilot

gate-sync-pilot: gate-phase-7-source
	$(PYTHON) scripts/phase7.py pilot-gate --kind sync
	$(PYTHON) scripts/release.py gate --kind sync-pilot
