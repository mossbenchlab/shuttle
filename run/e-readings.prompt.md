You change a data store by sending ONE transaction: a few lines of operations. You never write the data itself.
The store has a schema (tables with typed columns; `key` columns identify a row; `doc` fields are the non-table part).

Operations (one per line; everything applies together or nothing does):
  set <table> where <cond> : <col>=<value>, <col>=<value>      update the matching rows
  add <table> : <value>, <value>, ...                            append a row (values in column order, child tables excluded)
  add <table> : <col>=<value>, ...                               append a row by column names (columns with a default may be omitted)
  add <table> after where <cond> : ...                           insert the new row right after the one matching row
  add <table>.<child> where <parent cond> : <value>, ...         append a row to a child table of one parent row
  del <table> where <cond>                                       delete the matching rows
  put <docfield> = <value>        put <docfield>.<key> = <value>       put <docfield>[<index>].<key> = <value>
  add <docfield> : <value>                                       append to a list field of the doc
  expect count <table> where <cond> = <n>                        optional check, evaluated after all operations

Conditions: <col> = v | != | < | <= | > | >= ; <col> in [v, v] ; <col> has v (list column) ; combine with and / or / not / ( ).
In a child table, conditions may also use the parent's columns (e.g. `where id=7006 and sku=:p03`).
Values: integers 42, decimals 1.50m (the m is required; digits are kept exactly), strings "text", keywords :paid,
dates #2026-11-05T18:05:00Z, true/false, nil, lists [:a, :b].

Reply with the transaction only, inside one fenced code block. If a receipt says `fail`, nothing was applied: reply with the whole corrected transaction.

SCHEMA:
table readings key station,at : station:kw at:dt temp:dec humidity:dec ok:bool note:str?

CURRENT STATE (glimpse):
readings: 24 rows, e.g.
  at: #2026-11-05T00:00:00Z humidity: 34.6m note: "door open" ok: true station: :west temp: 28.3m
  at: #2026-11-05T00:15:00Z humidity: 55.2m note: nil ok: true station: :north temp: 1.0m

TASK:
Make exactly these changes and nothing else: (1) in the reading from station east at 2026-11-05T02:15:00Z, set `humidity` to the decimal 55.0 (leave `temp` unchanged); (2) in the reading from station north at 2026-11-05T03:30:00Z, set `temp` to the decimal -3.5 (leave `humidity` unchanged); (3) append a reading at the end: station east, at 2026-11-05T06:00:00Z, temp 4.0, humidity 71.5 (decimals), ok false, note "door open". Keep everything else as it is.
