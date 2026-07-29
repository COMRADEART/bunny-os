PYTHON ?= python3

.PHONY: audit installer-audit installer-schema validate test test-security test-broker test-shell test-launcher test-search test-workspace test-panel test-notifications test-approvals test-settings test-terminal test-accessibility test-performance test-desktop-security test-installer test-storage test-encryption test-dual-boot test-first-run test-app-distribution test-installer-security installer-performance build-developer-image build-shell-image build-shell-test-image build-live-image build-beta-image build-recovery-image inspect-image inspect-shell-image verify-install-media vm-smoke vm-shell-smoke vm-install-smoke vm-encrypted-install vm-upgrade-test sbom shell-sbom security-scan shell-security-scan license-scan shell-license-scan performance-baseline gate gate-phase-2 gate-phase-3

audit:
	$(PYTHON) scripts/task.py audit

installer-audit:
	$(PYTHON) scripts/task.py installer-audit

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
