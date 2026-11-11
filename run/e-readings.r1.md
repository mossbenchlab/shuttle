```
set readings where station=:east and at=#2026-11-05T02:15:00Z : humidity=55.0m
set readings where station=:north and at=#2026-11-05T03:30:00Z : temp=-3.5m
add readings : :east, #2026-11-05T06:00:00Z, 4.0m, 71.5m, false, "door open"
```
