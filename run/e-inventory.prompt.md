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
table items key sku : sku:kw name:str qty:int reorder:int price:dec updated:dt

CURRENT STATE (glimpse):
items: 24 rows, e.g.
  name: "hinge M6" price: 15.80m qty: 27 reorder: 11 sku: :p25 updated: #2026-10-24T14:53:00Z
  name: "plug M4" price: 31.60m qty: 0 reorder: 36 sku: :p45 updated: #2026-10-23T12:07:00Z

TASK:
Make exactly these changes and nothing else: (1) for the item with sku p44, set `reorder` to 12 (leave `qty` unchanged); (2) for the item with sku p02, set `price` to the decimal 7.50; (3) remove the item with sku p28. Keep every other item and field as it is, in the same order.
