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
doc version:str date:dt summary:str changes:list<map> contributors:list<str> signed:bool

CURRENT STATE (glimpse):
doc: changes:   - {issue: 812, kind: :feature, title: "Delta sync"}   - affects: ["2.3.0", "2.3.1"]     issue: 790     kind: :fix     title: "Queue no longer stalls"   - kind: :removal     replacement: {guide: nil, use: "v2 tokens"}     title: "v1 tokens" contributors: ["mina", "j. ortiz"] date: #2026-11-02T06:30:00Z signed: true summary: |   Faster sync.   Fixes the "stuck queue" bug.   Drops support for v1 tokens. version: "2.4.0"

TASK:
Make exactly these changes and nothing else: (1) in `summary`, change the third line to "Drops support for v1 and v0 tokens." (the summary still ends with a line break); (2) in the removal change, set `guide` to the string "https://example.org/migrate"; (3) in the feature change, set `issue` to 813. Keep everything else as it is.
