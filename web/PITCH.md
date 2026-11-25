# iScale pitch runbook (26 Nov 2026)

Everything below runs from the repo root unless it says `cd web`.

## The morning of the pitch (15 min)

```bash
git pull && cd web && pnpm install
pnpm rehearse --build          # builds, then clicks through the whole story on its own backend
```

`ALL PASSED` → you're good. Screenshots and `rehearsal/report.pdf` are in `web/rehearsal/`.
Any `FAIL` → read `web/rehearsal/report.txt`, fix or cut that step from the talk.

## Start clean for the pitch

A fresh data folder gives first-run setup and an empty project list. Use a new one each rehearsal.

```bash
# terminal 1: backend with a fresh, separate data folder (never your real data)
CIVIL_DATA_DIR=$HOME/iscale-pitch-$(date +%H%M) uv run civil serve        # :8765

# terminal 2: the built site (fast, no compile pauses)
cd web && HOST=0.0.0.0 CIVIL_ALLOWED_HOSTS=$(hostname -I | awk '{print $1}') pnpm serve
```

Then in the laptop browser open **`http://<laptop-ip>:3000`** (not localhost, so the QR codes work for phones).
`hostname -I` prints the IP. On macOS use `ipconfig getifaddr en0`.

1. `/login` shows **Set up iScale for your team**. Company: *Bang Sue District Works*, your name, username `presenter`.
2. Press **Load demo street**. Processing takes ~20–30 s: talk over it (step 1 of the story).
3. **Team** (left rail) → add *Somchai K.*, username `crew.somchai`, role Engineer. Scan the QR with the phone,
   sign in as `crew.somchai` on the phone. Do this **before** going on stage; the phone stays signed in.

## The story (7 minutes)

| # | Where | Click | Say |
|---|---|---|---|
| 1 | Overview | (demo processing) | "A car with a phone drove 242 m of Bang Sue. No inspector walked it." |
| 2 | Overview | point at the headline | "89 out of 100, 10 open defects, USD 2,585 to fix. Every number is measured, not guessed." |
| 3 | Overview | a red/orange count in *Open defects by type* | "Every count opens the evidence." → Findings table, filtered |
| 4 | Map | click the high-severity pothole | "7.8 cm deep, 0.87 m across, 31 L of missing asphalt. Measured from the 3D scan." |
| 5 | Drawer | scan the QR with the phone | "The crew gets it on their phone." Phone shows the job card: address, materials in baht, Navigate |
| 6 | Fix first | — | "Ranked by severity × safety × traffic: the most dangerous defect on the busiest road comes first." |
| 7 | Repair plan | drag the budget slider down | "Only have USD 1,500? This is what you fund; the rest waits." |
| 8 | Repair plan | **Create work order** | "One click, the crew has the list." |
| 9 | Verification | **Mark completed** → **Run verification** | "The after-drive checks the work: 6 fixed, 4 still there. Send the crew back." |
| 10 | Report | **Print** | "One page for the council." |
| 11 | top bar | **ไทย** | "Built for Thai crews." Switch back with **EN**. |

## If something goes wrong

| Problem | Do this |
|---|---|
| No internet | Everything works except the map's street background (plain grey with a notice). Keep going. |
| Phone can't open the QR link | Venue wifi may isolate devices. Turn on the **phone's hotspot**, join it with the laptop, restart terminal 2 (new IP), reload the laptop page. |
| Demo stuck processing | Check terminal 1 for errors. Stop both, start again with a new `CIVIL_DATA_DIR`. |
| "already linked to another device" | That username was claimed by another browser. Use a new username, or Team → Reset device. |
| A page errors | Use the old UI at `http://127.0.0.1:8765/` (static/) as a fallback for that step. |
| `pnpm serve` says port in use | `PORT=3001 pnpm serve`, open `:3001`. |

## Numbers to know (demo street)

242 m surveyed · 10 segments of 25 m · condition 89/100 (Good) · 10 open defects (4 high) ·
repair estimate USD 2,585 incl. USD 1,200 mobilisation · after repairs: 6 verified, 4 still present.
Plan costs are USD; materials on the job card are THB.
