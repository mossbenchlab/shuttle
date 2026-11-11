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
doc service:str version:str debug:bool limits:map flags:list<kw>
table endpoints key path : path:str method:kw auth:bool rate:int burst:int

CURRENT STATE (glimpse):
endpoints: 6 rows, e.g.
  auth: true burst: 92 method: :put path: "/v1/items" rate: 14
  auth: true burst: 85 method: :get path: "/v1/items/{id}" rate: 116
doc: debug: false flags: [:cache, :gzip, :audit] limits: {max_conn: 512, retries: 3, timeout_ms: 3000} service: "catalog-api" version: "3.2.0"

TASK:
Make exactly these changes and nothing else: (1) set `timeout_ms` in `limits` to 4500 (leave `max_conn` and `retries` unchanged); (2) for the endpoint /v1/upload set `burst` to 69 (leave `rate` unchanged); (3) add the flag beta at the end of `flags`. Keep everything else as it is.
