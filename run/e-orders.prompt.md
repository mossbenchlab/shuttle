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
table orders key id : id:int placed:dt status:kw priority:int tags:list<kw>=[] lines:lines
table orders.lines : sku:kw qty:int unit_price:dec

CURRENT STATE (glimpse):
orders: 14 rows, e.g.
  id: 7001 lines: table(qty, sku, unit_price)   8 :p34 28.90m   2 :p44 18.13m   1 :p30 4.26m placed: #2026-11-03T13:05:00Z priority: 4 status: :packed tags: [:fragile, :rush]
  id: 7002 lines: table(qty, sku, unit_price)   10 :p08 9.38m   9 :p48 8.17m   6 :p52 21.70m placed: #2026-11-04T20:33:00Z priority: 5 status: :shipped tags: [:bulk, :fragile]

TASK:
Make exactly these changes and nothing else: (1) append a line to order 7006 with sku p03, qty 2, unit_price 3.10 (decimal); (2) set the status of order 7010 to paid; (3) insert a new order right after order 7003 with id 7099, placed 2026-11-05T18:05:00Z, status new, priority 2, no tags, and one line with sku p41, qty 1, unit_price 12.00 (decimal, keep the trailing zeros). Keep everything else as it is.
