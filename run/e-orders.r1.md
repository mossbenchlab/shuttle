```
add orders.lines where id=7006 : :p03, 2, 3.10m
set orders where id=7010 : status=:paid
add orders after where id=7003 : id=7099, placed=#2026-11-05T18:05:00Z, status=:new, priority=2, tags=[]
add orders.lines where id=7099 : :p41, 1, 12.00m
```
