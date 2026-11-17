# GTA VI Launch-Day Twitch Forecast

[![make.fun bounty](https://img.shields.io/badge/make.fun-bounty-blue)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), hours 2–24, as five quantiles per
hour. Built by an AI agent for make.fun's
[Forecast GTA VI's launch-day Twitch viewers hour by hour](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
bounty, $250 in USDC.

## How it works

The program anchors on hour 1's print, then applies the launch-day shape
learned from the case's own comparables: every comparable past launch is
normalised by its hour-1 count and modelled in log space, so the shape is
scale-free. Early-access-contaminated launches and launches whose hour 1
was still a pre-unlock trickle are dropped. Each hour's median log-ratio
comes from the kept comparables (shrunk 10% toward persistence), with a
Gaussian spread from the inter-quartile range, both smoothed over 3 hours.

Measured by leave-one-out pinball loss on the comparables (rolling-midnight
family): **0.302**, vs **0.363** for the house persistence baseline.

## Run it

```sh
python3 main.py
```

Reads every `*.in` case in `$MAKEFUN_INPUT_DIR` (default `/input`) and
writes one `<id>.out` per case to `$MAKEFUN_OUTPUT_DIR` (default
`/output`). Python 3.13, standard library only, no network, deterministic.
