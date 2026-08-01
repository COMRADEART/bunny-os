PYTHON ?= python3

.PHONY: audit installer-audit installer-schema phase5-audit phase-5-baseline import-beta-feedback triage-report release-dashboard validate test test-security test-broker test-shell test-launcher test-search test-workspace test-panel test-notifications test-approvals test-settings test-terminal test-accessibility test-performance test-desktop-security test-installer test-storage test-encryption test-dual-boot test-first-run test-app-distribution test-installer-security test-phase5 test-update-security test-rollbacks test-recovery test-migrations test-hardware-report test-diagnostics test-redaction test-crash-reporting test-network-privacy test-application-catalogue test-release-signing test-installer-regressions test-update-regressions test-multi-user test-bunny-disabled test-local-only test-privacy-regressions test-accessibility-regressions test-hardware-matrix long-run-tests installer-performance build-developer-image build-shell-image build-shell-test-image build-live-image build-beta-image build-recovery-image build-stable-rc sign-stable-rc verify-stable-rc stable-artifacts inspect-image inspect-shell-image verify-install-media vm-smoke vm-shell-smoke vm-install-smoke vm-encrypted-install vm-upgrade-test vm-rollback-test vm-recovery-test reproducible-build-check sbom shell-sbom security-scan shell-security-scan license-scan shell-license-scan malware-scan performance-baseline gate gate-phase-2 gate-phase-3 gate-phase-4 gate-public-beta gate-phase-5 gate-stable-candidate gate-stable-release phase7-audit phase-7-baseline test-oem test-factory test-device-identity test-enrolment test-policy test-fleet test-multitenancy test-sync test-sync-crypto test-device-revocation test-remote-wipe test-airgap test-kiosk test-decommission test-pilot fleet-simulation pilot-readiness build-oem-image gate-phase-7-source gate-phase-7 gate-oem-pilot gate-enterprise-pilot gate-sync-pilot gate-dev-qualification dev-qualification-gaps qualification-compare release-blocker-baseline vulnerability-position reachability-review package-minimisation-check licence-gate independent-builder-prepare reproducibility-compare development-signing-drill signing-roles build-qualification-candidate build-independent-recovery validate-release-manifest test-installation-matrix test-encryption-matrix test-update-matrix test-rollback-matrix test-recovery-matrix test-preservation-matrix test-accessibility-matrix validate-hardware-evidence validate-independent-reviews stable-evidence-report pilot-closure-assertion test-release-closure qualification-evidence-baseline independent-builder-ci-manifest collect-builder-record verify-builder-independence compare-independent-builds acquire-cve-sources validate-cve-acquisition analyse-cve-symbols generate-reachability-packages collect-hardware-evidence accessibility-evidence-plan validate-accessibility-evidence two-person-development-signing-drill qualification-candidate-readiness gate-source gate-qualification-candidate test-qualification-evidence test-reachability test-review-evidence mirror-base-image verify-retained-base build-builder-image verify-builder-image resolve-package-lock materialise-package-snapshot verify-package-snapshot verify-input-locks hermetic-build image-finalisation machine-identity-check mutable-state-check rpmdb-determinism-check font-cache-determinism-check intended-selinux-manifest deterministic-sbom inspect-sqlite-databases compare-sqlite-logical compare-sqlite-pages compare-rpm-headers finalise-package-databases sqlite-determinism-check test-rpmdb-rebuild test-libdnf-history-rebuild complete-local-comparison publish-retained-base publish-builder-image publish-package-snapshot verify-published-inputs cold-pull-input-test create-reproducibility-target dispatch-hosted-h1 dispatch-hosted-h2 collect-local-bundle import-three-builder-evidence local-hermetic-repeatability dispatch-hosted-reproducibility import-reproducibility-evidence compare-three-builds toolchain-independence reproducibility-gate test-supplychain tpm-baseline tpm-no-device-control tpm-crb-cold tpm-tis-cold tpm-crb-reused-state tpm-tis-reused-state tpm-firmware-control tpm-known-good-disk-control tpm-grub-isolation tpm-reset-classify tpm-regression-matrix tpm-evidence-gate tpm-qualification-gate test-tpm tpm-summarise-matrix tpm-render-regression-report tpm-retain-bulky-evidence

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

# --- Qualification evidence closure -------------------------------------------
# Every target here fails closed. Several are expected to exit 2 indefinitely:
# they need a hosted CI run, a physical device, an external reviewer or a second
# signer, and no amount of running them again produces one.

qualification-evidence-baseline:
	$(PYTHON) scripts/release.py qualification-evidence-baseline

# Reports whether the hosted workflow records everything an independent builder
# must record, and separately whether it has ever run. A prepared workflow is not
# an executed one.
independent-builder-ci-manifest:
	$(PYTHON) scripts/release.py independent-builder-ci-manifest

# Run on each builder. BUNNY_BUILDER_ID names it; BUNNY_BASE_IMAGE must be the
# pinned digest, because a record naming a mutable tag is refused.
collect-builder-record:
	$(PYTHON) scripts/release.py collect-builder-record --builder-id "$${BUNNY_BUILDER_ID:-local}"

verify-builder-independence:
	$(PYTHON) scripts/release.py verify-builder-independence

compare-independent-builds:
	$(PYTHON) scripts/release.py compare-independent-builds

# Emits the acquisition plan. It does not download anything: the environments
# that run these gates have no route to Fedora infrastructure, and a plan can be
# reviewed before it is run.
acquire-cve-sources:
	$(PYTHON) scripts/release.py acquire-cve-sources

validate-cve-acquisition:
	$(PYTHON) scripts/release.py validate-cve-acquisition

# Set BUNNY_SYSROOT to a mounted deployment to analyse the shipped binaries.
analyse-cve-symbols:
	$(PYTHON) scripts/reachability.py analyse-symbols $${BUNNY_SYSROOT:+--sysroot $$BUNNY_SYSROOT}

generate-reachability-packages:
	$(PYTHON) scripts/reachability.py generate-findings
	$(PYTHON) scripts/reachability.py generate-packages
	$(PYTHON) scripts/release.py cve-disposition

collect-hardware-evidence:
	$(PYTHON) scripts/release.py collect-hardware-evidence

accessibility-evidence-plan:
	$(PYTHON) scripts/release.py accessibility-evidence-plan

validate-accessibility-evidence:
	$(PYTHON) scripts/release.py validate-accessibility-evidence

# Runs the drill, then validates what it recorded. BUNNY_DRILL_ARTIFACT should
# name a real built archive; without one the drill uses a synthetic artifact and
# says so.
two-person-development-signing-drill:
	$(PYTHON) scripts/two_person_drill.py $${BUNNY_DRILL_ARTIFACT:+--artifact $$BUNNY_DRILL_ARTIFACT}
	$(PYTHON) scripts/release.py two-person-development-signing-drill

qualification-candidate-readiness:
	$(PYTHON) scripts/release.py qualification-candidate-readiness

# The source gate is a statement about the repository and nothing else. It has
# passed for most of this project's life and the project has never been close to
# a release; keeping it separate is what stops the two being confused.
gate-source:
	$(PYTHON) scripts/release.py gate --kind source

# A blocking candidate gate does not forbid building an artifact. It forbids
# calling one release-qualified.
gate-qualification-candidate:
	$(PYTHON) scripts/release.py gate --kind qualification-candidate

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

# --- Reproducible build remediation -----------------------------------------
# Every target has a Python entry point; `make` is unavailable on the Windows
# development host, so the equivalent command is given in each report.

mirror-base-image:
	bash scripts/supply-chain/mirror-base-image.sh --upstream "$${BUNNY_BASE_IMAGE:?set BUNNY_BASE_IMAGE to a digest-pinned reference}"

verify-retained-base:
	$(PYTHON) scripts/supply-chain/verify-retained-base.py

build-builder-image:
	bash scripts/supply-chain/build-builder-image.sh

verify-builder-image:
	$(PYTHON) scripts/supply-chain/verify-builder-image.py

resolve-package-lock:
	$(PYTHON) scripts/supply-chain/resolve-package-lock.py --profile "$${BUNNY_PROFILE:-beta}" --base-layout "$${BUNNY_BASE_LAYOUT:?set BUNNY_BASE_LAYOUT}" --download-dir "$${BUNNY_DOWNLOAD_DIR:-/var/tmp/bunny-package-download}"

materialise-package-snapshot:
	bash scripts/supply-chain/materialise-package-snapshot.sh --snapshot-id "$${BUNNY_SNAPSHOT_ID:?set BUNNY_SNAPSHOT_ID}" --packages "$${BUNNY_DOWNLOAD_DIR:-/var/tmp/bunny-package-download}"

verify-package-snapshot:
	$(PYTHON) scripts/supply-chain/verify-package-snapshot.py

verify-input-locks:
	$(PYTHON) scripts/supplychain.py verify-input-locks

hermetic-build:
	BUNNY_HERMETIC_BUILD=1 BUNNY_ARCHIVE_ONLY=1 bash build/scripts/build-image.sh "$${BUNNY_PROFILE:-beta}"

image-finalisation:
	bash build/scripts/finalise-image.sh --epoch "$${SOURCE_DATE_EPOCH:?set SOURCE_DATE_EPOCH}" --report build/out/qualification/finalisation.json

machine-identity-check:
	$(PYTHON) scripts/supplychain.py machine-identity-check --dimensions "$${BUNNY_DIMENSIONS:-build/out/qualification/dimensions.json}"

mutable-state-check:
	$(PYTHON) scripts/supplychain.py mutable-state-check --dimensions "$${BUNNY_DIMENSIONS:-build/out/qualification/dimensions.json}"

rpmdb-determinism-check:
	$(PYTHON) scripts/reproducibility/check_package_state.py --dimensions "$${BUNNY_DIMENSIONS:-build/out/qualification/dimensions.json}" --kind rpmdb

font-cache-determinism-check:
	$(PYTHON) scripts/reproducibility/check_package_state.py --dimensions "$${BUNNY_DIMENSIONS:-build/out/qualification/dimensions.json}" --kind fontconfig

intended-selinux-manifest:
	$(PYTHON) scripts/reproducibility/collect_intended_selinux.py --archive "$${BUNNY_ARCHIVE:?set BUNNY_ARCHIVE}" --output build/out/qualification/intended-selinux.json

deterministic-sbom:
	$(PYTHON) scripts/reproducibility/check_package_state.py --dimensions "$${BUNNY_DIMENSIONS:-build/out/qualification/dimensions.json}" --kind sbom

inspect-sqlite-databases:
	$(PYTHON) scripts/reproducibility/inspect_sqlite.py --database "$${BUNNY_RPMDB:?set BUNNY_RPMDB}" --owner rpm --database "$${BUNNY_HISTORY:?set BUNNY_HISTORY}" --owner libdnf5 --output build/out/reproducibility/sqlite-inspection.json --require-integrity

compare-sqlite-logical:
	$(PYTHON) scripts/reproducibility/compare_sqlite_logical.py --first "$${BUNNY_FIRST:?set BUNNY_FIRST}" --second "$${BUNNY_SECOND:?set BUNNY_SECOND}" --output build/out/reproducibility/sqlite-logical-diff.json

compare-sqlite-pages:
	$(PYTHON) scripts/reproducibility/compare_sqlite_pages.py --first "$${BUNNY_FIRST:?set BUNNY_FIRST}" --second "$${BUNNY_SECOND:?set BUNNY_SECOND}" --output build/out/reproducibility/sqlite-structural-diff.json

compare-rpm-headers:
	$(PYTHON) scripts/reproducibility/diff_rpm_headers.py --first "$${BUNNY_FIRST:?set BUNNY_FIRST}" --second "$${BUNNY_SECOND:?set BUNNY_SECOND}" --output build/out/reproducibility/rpm-header-diff.json

finalise-package-databases:
	bash build/scripts/finalise-package-databases.sh --report build/out/qualification/package-databases.json

sqlite-determinism-check test-rpmdb-rebuild test-libdnf-history-rebuild:
	$(PYTHON) scripts/reproducibility/evaluate_database_approaches.py --command $@ --rpmdb "$${BUNNY_RPMDB:?set BUNNY_RPMDB to an extracted rpmdb.sqlite}" --history "$${BUNNY_HISTORY:?set BUNNY_HISTORY to an extracted transaction_history.sqlite}" --trials "$${BUNNY_TRIALS:-3}" --report "build/out/reproducibility/$@.json"

complete-local-comparison:
	bash scripts/supply-chain/local-hermetic-repeatability.sh --mode qualification

local-hermetic-repeatability:
	bash scripts/supply-chain/local-hermetic-repeatability.sh --mode "$${BUNNY_COMPARISON_MODE:-qualification}"

publish-retained-base:
	bash scripts/supply-chain/publish-retained-inputs.sh --kind base --registry "$${BUNNY_REGISTRY:-ghcr.io/comradeart}"

publish-builder-image:
	bash scripts/supply-chain/publish-retained-inputs.sh --kind builder --registry "$${BUNNY_REGISTRY:-ghcr.io/comradeart}"

publish-package-snapshot:
	bash scripts/supply-chain/publish-retained-inputs.sh --kind snapshot --registry "$${BUNNY_REGISTRY:-ghcr.io/comradeart}"

verify-published-inputs:
	$(PYTHON) scripts/supply-chain/verify-published-inputs.py --publication build/inputs/input-publication-lock.json

cold-pull-input-test:
	gh workflow run verify-reproducible-inputs.yml --repo COMRADEART/bunny-os --field publication="$${BUNNY_PUBLICATION_COMMIT:-$$(git rev-parse HEAD)}"

create-reproducibility-target:
	$(PYTHON) scripts/supply-chain/create-reproducibility-target.py --output build/inputs/qualification-target.json

# The dispatch ref selects which branch's *workflow file* runs; the commit
# being built is pinned separately by the commit field. Without an explicit
# ref, gh dispatches the default branch's copy, which silently ignores any
# workflow fix that has not merged yet.
dispatch-hosted-h1:
	gh workflow run hermetic-builder.yml --repo COMRADEART/bunny-os --ref "$${BUNNY_DISPATCH_REF:-main}" --field commit="$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}" --field label=H1

dispatch-hosted-h2:
	gh workflow run hermetic-builder.yml --repo COMRADEART/bunny-os --ref "$${BUNNY_DISPATCH_REF:-main}" --field commit="$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}" --field label=H2

collect-local-bundle:
	bash scripts/supply-chain/collect-local-bundle.sh --commit "$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}"

import-three-builder-evidence:
	$(PYTHON) scripts/release.py import-hosted-builder-evidence --artifact-dir "$${BUNNY_ARTIFACT_DIR:?set BUNNY_ARTIFACT_DIR}" --candidate-commit "$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}" --local-artifact-dir "$${BUNNY_LOCAL_ARTIFACT_DIR:-build/out/qualification/local-bundle}"

dispatch-hosted-reproducibility:
	gh workflow run hermetic-builder.yml --repo COMRADEART/bunny-os --field commit="$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}"

import-reproducibility-evidence:
	$(PYTHON) scripts/release.py import-hosted-builder-evidence --artifact-dir "$${BUNNY_ARTIFACT_DIR:?set BUNNY_ARTIFACT_DIR}" --candidate-commit "$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}"

compare-three-builds:
	$(PYTHON) scripts/supplychain.py compare-three-builds

toolchain-independence:
	$(PYTHON) scripts/supplychain.py toolchain-independence

reproducibility-gate:
	$(PYTHON) scripts/supplychain.py reproducibility-gate --independent

test-supplychain:
	$(PYTHON) -m unittest discover -s tests/supplychain -t .

# ---------------------------------------------------------------------------
# Installed-system qualification. Every target reads its authority from
# qualification/installed-system/evidence-context.json through
# release/installed.py — no target decides for itself what is being tested.
# The disk artifacts and scenario disks live outside the repository by size;
# BUNNY_INSTALLABLES_DIR and BUNNY_SCENARIO_DISKS name where.

ISQ := qualification/installed-system
ISQ_SCRIPTS := $(ISQ)/scripts
BUNNY_INSTALLABLES_DIR ?= /var/tmp/bunny-installables-out
BUNNY_SCENARIO_DISKS ?= /var/tmp/bunny-install-disks

collect-installer-toolchain:
	$(PYTHON) build/installer/scripts/collect-toolchain-lock.py --output build/installer/toolchain.lock.json

build-installable-images:
	bash $(ISQ_SCRIPTS)/build_installables.sh --archive "$${BUNNY_QUALIFIED_ARCHIVE:?set BUNNY_QUALIFIED_ARCHIVE}" --expected-archive "$${BUNNY_ARCHIVE_DIGEST:?set BUNNY_ARCHIVE_DIGEST}" --commit "$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}" --output "$(BUNNY_INSTALLABLES_DIR)"

build-installable-qcow2 build-installable-raw: build-installable-images

create-installed-evidence-context:
	$(PYTHON) $(ISQ_SCRIPTS)/create_evidence_context.py --source-commit "$${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT}" --source-archive-digest "$${BUNNY_ARCHIVE_DIGEST:?set BUNNY_ARCHIVE_DIGEST}" --installables "$(BUNNY_INSTALLABLES_DIR)/installables.json" --installation-artifact "bunny-os-$$(echo $${BUNNY_CANDIDATE_COMMIT} | head -c 12).qcow2"

qemu-install-blank:
	bash $(ISQ_SCRIPTS)/install_to_disk.sh --mode blank --size 24G --target "$(BUNNY_SCENARIO_DISKS)/blank.raw" --image "$${BUNNY_IMAGE:?set BUNNY_IMAGE}" --record $(ISQ)/evidence/installs/blank.json

qemu-install-offline:
	bash $(ISQ_SCRIPTS)/install_to_disk.sh --mode offline --size 24G --target "$(BUNNY_SCENARIO_DISKS)/offline.raw" --image "$${BUNNY_IMAGE:?set BUNNY_IMAGE}" --record $(ISQ)/evidence/installs/offline.json

qemu-install-encrypted:
	bash $(ISQ_SCRIPTS)/install_encrypted.sh --size 24G --target "$(BUNNY_SCENARIO_DISKS)/encrypted.raw" --image "$${BUNNY_IMAGE:?set BUNNY_IMAGE}" --record $(ISQ)/evidence/installs/encrypted.json

qemu-install-interrupted:
	bash $(ISQ_SCRIPTS)/install_to_disk.sh --mode interrupted --interrupt-after 25 --size 24G --target "$(BUNNY_SCENARIO_DISKS)/interrupted.raw" --image "$${BUNNY_IMAGE:?set BUNNY_IMAGE}" --record $(ISQ)/evidence/installs/interrupted.json

qemu-first-boot:
	$(PYTHON) $(ISQ_SCRIPTS)/run_scenario.py --scenario $(ISQ)/scenarios/first-boot.json --disk "$(BUNNY_INSTALLABLES_DIR)/bunny-os-$$(echo $${BUNNY_CANDIDATE_COMMIT:?set BUNNY_CANDIDATE_COMMIT} | head -c 12).qcow2"

qemu-applied-selinux:
	$(PYTHON) $(ISQ_SCRIPTS)/collect_applied_selinux.py --disk "$${BUNNY_BOOTED_DISK:?set BUNNY_BOOTED_DISK}" --output $(ISQ)/evidence/collections/applied-selinux.json
	$(PYTHON) $(ISQ_SCRIPTS)/compare_selinux_manifests.py --intended "$${BUNNY_INTENDED_SELINUX:?set BUNNY_INTENDED_SELINUX}" --applied $(ISQ)/evidence/collections/applied-selinux.json --expected-differences $(ISQ)/fixtures/selinux-expected-differences.json --output $(ISQ)/evidence/collections/selinux-comparison.json

qemu-network-privacy:
	$(PYTHON) $(ISQ_SCRIPTS)/analyze_network_capture.py "$${BUNNY_PCAP:?set BUNNY_PCAP}" --expected $(ISQ)/fixtures/expected-network-traffic.json --output $(ISQ)/evidence/collections/network-privacy.json

build-update-fixtures:
	$(PYTHON) $(ISQ_SCRIPTS)/update_manifest_tests.py --output-dir $(ISQ)/evidence/collections

qemu-update:
	$(PYTHON) $(ISQ_SCRIPTS)/update_rollback_offline.py stage --disk "$${BUNNY_UPDATE_DISK:?set BUNNY_UPDATE_DISK}" --image-archive "$${BUNNY_NEXT_ARCHIVE:?set BUNNY_NEXT_ARCHIVE}" --record $(ISQ)/evidence/collections/update-to-next.json

qemu-rollback:
	$(PYTHON) $(ISQ_SCRIPTS)/update_rollback_offline.py rollback --disk "$${BUNNY_UPDATE_DISK:?set BUNNY_UPDATE_DISK}" --record $(ISQ)/evidence/collections/rollback.json

installed-system-matrix:
	@echo "The matrix is driven by the operator scripts recorded in the evidence"
	@echo "records themselves; this target imports whatever evidence exists:"
	$(PYTHON) $(ISQ_SCRIPTS)/import_matrix_results.py

installed-evidence-gate:
	$(PYTHON) $(ISQ_SCRIPTS)/import_matrix_results.py --dry-run

collect-physical-hardware:
	@echo "Run qualification/hardware/collect-*.sh ON THE TARGET DEVICE and submit"
	@echo "through: python scripts/release.py validate-hardware-evidence"
	@echo "No device is connected to this build host; there is nothing to collect here."
	@exit 2

test-installed:
	$(PYTHON) -m unittest discover -s tests/installed -t .

# TPM boot-reset investigation and qualification. Every target reads its
# authority from qualification/tpm/evidence-context.json through
# qualification/tpm/scripts/tpm_context.py — no target decides for itself
# what is being tested, and a record about any other disk, firmware image,
# emulator build or scenario version is refused as stale. The VM-running
# targets require QEMU/KVM, OVMF and swtpm on this machine (the WSL
# builder); the gates and tests run anywhere.
TPMQ := qualification/tpm
TPMQ_SCRIPTS := $(TPMQ)/scripts

tpm-baseline:
	$(PYTHON) $(TPMQ_SCRIPTS)/tpm_context.py

tpm-no-device-control:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only no-tpm-cold

tpm-crb-cold:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only crb-fresh-cold

tpm-tis-cold:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only tis-fresh-cold

tpm-crb-reused-state:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only crb-reused-cold

tpm-tis-reused-state:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only tis-reused-cold

tpm-firmware-control:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only fw-only-crb --only fw-only-tis

tpm-known-good-disk-control:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only fedora-no-tpm --only fedora-crb-fresh-repro --only fedora-crb-continue

tpm-grub-isolation:
	bash $(TPMQ_SCRIPTS)/extract_boot_chain.sh "$${BUNNY_QUALIFIED_QCOW2:?set BUNNY_QUALIFIED_QCOW2}" "$${BUNNY_QCOW2_DIGEST:?set BUNNY_QCOW2_DIGEST}" "$${BUNNY_BOOT_CHAIN_OUT:-build/out/tpm/boot-chain}"

tpm-reset-classify:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py --only crb-fresh-repro-stop --only tis-fresh-repro-stop

tpm-regression-matrix:
	$(PYTHON) $(TPMQ_SCRIPTS)/run_matrix.py

tpm-summarise-matrix:
	$(PYTHON) $(TPMQ_SCRIPTS)/summarise_matrix.py --evidence-root $(TPMQ)/evidence

tpm-render-regression-report:
	$(PYTHON) $(TPMQ_SCRIPTS)/render_regression_report.py --evidence-root $(TPMQ)/evidence --report TPM_BOOT_REGRESSION_REPORT.md

tpm-retain-bulky-evidence:
	$(PYTHON) $(TPMQ_SCRIPTS)/retain_bulky_evidence.py --evidence-root $(TPMQ)/evidence --trace-root "$${BUNNY_TPM_TRACE_ROOT:-/root/tpm-traces}"

tpm-evidence-gate:
	$(PYTHON) $(TPMQ_SCRIPTS)/import_tpm_results.py --dry-run

tpm-qualification-gate:
	$(PYTHON) $(TPMQ_SCRIPTS)/import_tpm_results.py

test-tpm:
	$(PYTHON) -m unittest discover -s tests/tpm -t .
