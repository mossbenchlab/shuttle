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
doc title:str term:kw year:int instructor:map
table students key id : id:int name:str score:dec grade:kw late:int absent:int

CURRENT STATE (glimpse):
students: 14 rows, e.g.
  absent: 2 grade: :d id: 601 late: 3 name: "Emi Mori" score: 97.47m
  absent: 3 grade: :b id: 602 late: 5 name: "Kai Ono" score: 73.38m
doc: instructor:   hours: "Tue 14:00-16:00"   name: "K. Tanaka"   office: "B-214" term: :fall title: "Data Structures" year: 2026

TASK:
Make exactly these changes and nothing else: (1) for student 606 set `late` to 3 (leave `absent` unchanged); (2) for student 609 set `score` to the decimal 88.50 (keep the trailing zero); (3) remove student 612. Keep everything else as it is.
