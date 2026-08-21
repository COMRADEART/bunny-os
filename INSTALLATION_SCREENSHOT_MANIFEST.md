# Installation screenshot evidence manifest

Date: 2026-08-16  
Evidence root: `qualification/installer-journeys/evidence/`  
Every screenshot below was taken from outside the guest through QMP
(`screendump`), on a schedule bound to the run, and has been looked at — the
descriptions are of the pixels, not of what the harness intended to happen.

## Why each driven journey has exactly two

The §54 schedule (`60 150 300 600 900 1200` seconds) was written when an
install was expected to take twenty-odd minutes. A driven journey completes
in three to four, and the harness powers the machine off as soon as the
driver reports its outcome — so shots from t300 onward never fire. Journey D
refuses at 54 s and has none at all. An undriven run that idled at the
welcome screen collected all six, which is how the schedule's assumption was
caught. The harness accepts `BUNNY_INSTALL_SHOTS` for denser future runs;
the collected evidence stands as taken.

## Manifest

| File | Shows | sha256 |
|---|---|---|
| `journey-a/screens/t60.png` | "Where to install": three candidates with per-disk annotations — `/dev/loop0` "The selected disk is read-only", `/dev/zram0` "At least 40 GiB is required", `/dev/vda` "Appears to be empty"; Companion says "I need to know where to install. I won't change anything until you say so." | `289c4323…f246be`* |
| `journey-a/screens/t150.png` | "Installing": seven-step plan (Getting the disk ready ◆ … Finishing up), Now/Detail rows live ("Checking the plan"), Cancel present; Companion: "I'm setting things up now." | `5ff57807…be2df5`* |
| `journey-b/screens/t60.png` | Companion-presentation stage at **200 % text on 1024×768** — visibly larger type than journey A at the same stage; "How much of Bunny: Full — selected" | `54bbe933…ae1388`* |
| `journey-b/screens/t150.png` | "Installing" at 200 % text; layout intact at the declared minimum screen | `0d7132ef…4673ff`* |
| `journey-c/screens/t60.png` | "Installing" already at t60 — the unencrypted path reaches the install stage fastest; network indicator present in the top bar | `30c1d21d…f246be`* |
| `journey-c/screens/t150.png` | "Installing", Getting the disk ready | `b989a031…02f65e8`* |
| `journey-c-offline/screens/t60.png` | Same install screen with **no network indicator in the top bar** — the machine has no NIC; compare `journey-c/screens/t60.png` | `7170b81f…dca1ce`* |
| `journey-c-offline/screens/t150.png` | "Installing", offline run | `97a4bd79…23b11f`* |
| `first-boot/screens/b1-t300.png` | Boot 1 of the installed disk, no ISO: GDM greeter with the account created during setup — **Alex** — password field focused | `5f44012b…333384`* |
| `first-boot/screens/b2-t300.png` | Boot 2, same overlay: the same greeter again — persistence across a shutdown | `4009daaf…1789e0`* |

\* Full digests:

```
289c43231514af36d32fa47f384f9e8d23d1cf573c90a3b98a193dfa64872269  journey-a/screens/t60.png
5ff578071c0e833e9d8cbd4d81258c5d459850f6f99a1863a2d8672dc3be2df5  journey-a/screens/t150.png
54bbe933446664c579d951087ceff73e1d032444ca2437bc11d751b691ae1388  journey-b/screens/t60.png
0d7132ef74febd98b05f80bcf224efbc0b6f9fe6c6d7d1953dac73c8134673ff  journey-b/screens/t150.png
30c1d21d932a71f9f254500db895e23c7ede84293c130fc10b348af1f4f246be  journey-c/screens/t60.png
b989a031719389535c7eed38b504c59c4b17b43c91d0a4c42f64f7f6c02f65e8  journey-c/screens/t150.png
7170b81f256782f12203fe6a56972d14067b354f035ad278a515125707dca1ce  journey-c-offline/screens/t60.png
97a4bd79a1e3e441ed7b9b46add425c34f868634aee26c7e5a16cbd1ba23b11f  journey-c-offline/screens/t150.png
5f44012b3f65b88e9af243078e6e2aa220e8faae4c4c621f583ef7bec8333384  first-boot/screens/b1-t300.png
4009daaf04d6c9d53666d6b757536518076ed5103e2ec6e4866002505d1789e0  first-boot/screens/b2-t300.png
```

## Observations worth carrying, from looking

- In `journey-a/t60.png` the focused "Review what happens" button renders
  with very low contrast against the pane (light text on a light fill).
  A design-system follow-up, noted here because a manifest that only
  describes what flatters the run is not evidence.
- The two first-boot greeters differ only where they should (uptime-adjacent
  chrome); the account, prompt and layout are identical run to run.
- The journey-B shots are the §39 case on screen: smallest supported display,
  largest text, no clipped or truncated control in either frame.
