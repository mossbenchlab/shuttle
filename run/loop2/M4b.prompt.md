You change a data store by sending messages to an executor. A message is a few lines of operations. You never write the data itself; you never see the whole store.
The store has a schema (tables with typed columns; `key` columns identify a row; `doc` fields are the non-table part).

Reading (allowed in any message; results come back in the receipt):
  count <table> [where <cond>]
  show <table> [where <cond>] [cols a,b] [order <col> [asc|desc]] [limit n]      default limit 20
  get <table> where <cond>                                                    exactly one row
  sum <col> of <table> [where <cond>]

Writing (everything in one message applies together or nothing does):
  set <table> where <cond> : <col>=<value>, <col>=<value>      update EVERY matching row (one or thousands; `where true` = all rows)
  set <table> where <cond> : <col>+=<value>                     relative: numbers add (-= subtracts), lists append (-= removes); you need not know the current value
  add <table> : <value>, <value>, ...                            append a row (values in column order, child tables excluded)
  add <table> : <col>=<value>, ...                               append a row by column names (columns with a default may be omitted)
  add <table> after where <cond> : ...                           insert the new row right after the one matching row
  add <table>.<child> where <parent cond> : <value>, ...         append a row to a child table of one parent row
  del <table> where <cond>                                       delete the matching rows
  set? ... / del? ...                                            same, but matching no row is allowed (receipt shows set:0) — for guards like `and status!=:shipped`
  put <docfield> = <value>        put <docfield>.<key> = <value>       put <docfield>[<index>].<key> = <value>
  add <docfield> : <value>                                       append to a list field of the doc
  expect count <table> where <cond> = <n>                        check after all operations; also `expect sum <col> of <table> [where ...] >= v`
  tx <id> at <version>                                           optional first line: the message applies only if the store is still at that version

Conditions: <col> = v | != | < | <= | > | >= ; <col> in [v, v] ; <col> has v (list column) ; missing <col> (nil) ; combine with and / or / not / ( ).
In a child table, conditions may also use the parent's columns (e.g. `where id=7006 and sku=:p03`).
On a parent table, `any <child> where <cond>` / `none <child> where <cond>` select by the child rows (e.g. `set invoices where state=:open and any items where sku=:x9 : tags+=:flag`).
Aggregates can be used wherever a value is written; the executor computes them when the statement runs and echoes the value in the receipt:
  put stats.open = count tickets where state=:open        set invoices where id=42 : total = sum amount of invoices.items where id=42
Values: integers 42, decimals 1.50m (the m is required; digits are kept exactly), strings "text", keywords :paid,
dates #2026-11-05 or #2026-11-05T18:05:00Z, true/false, nil, lists [:a, :b], maps {k: v, k2: v2} (space after the colon).

Receipts: `ok v=<version> set:<rows> add:<rows> ... vid=<id>` followed by query results, or `fail line N: <why>` (nothing applied).
Reply with exactly one message per turn, inside one fenced code block. Prefer one conditional write over reading rows and writing them one by one.
When the store is in the required state, reply with the single word DONE (no code block).

SCHEMA:
doc audit:map
table orders key id : id:int status:kw=:unpaid due:dt total:dec tags:list<kw>=[] note:str? lines:lines
table orders.lines : sku:kw qty:int amount:dec

CURRENT STATE (glimpse; version 0):
orders: 50000 rows (124824 lines in all), e.g.
  due: #2026-03-14 id: 1000 lines: [{amount: 194.12m, qty: 4, sku: :p05}] note: nil status: :unpaid tags: [:a] total: 381.23m
  due: #2026-06-27 id: 1001 lines: [{amount: 163.58m, qty: 2, sku: :p02}] note: nil status: :paid tags: [] total: 166.40m
doc: audit: {paid: 0, policy: nil, shipped_total: 0m, unpaid: 0}

TASK:
In every UNPAID order, lines with sku :p03 must get qty 0. Each unpaid order that had at least one such line must also get the tag :p03-cancelled added. Change nothing else.
