# Stable hardware tiers

The tiers are Stable recommended, Stable supported, Best effort, Experimental, Unsupported, and Untested. Stable recommended requires physical clean/encrypted installation, update, rollback, recovery, graphics, network, audio, suspend/resume, and no open High-or-greater hardware issue. Stable supported requires tested installation/daily use and core devices with no Blocker/Critical issue. Best effort has limited evidence; Experimental has known gaps; Unsupported is explicit; Untested has no execution.

Detection and community expectation never promote a model. VM evidence cannot promote physical hardware. `operations/hardware.py` enforces these rules. The evidence database is empty, so no model is Recommended or Supported.
