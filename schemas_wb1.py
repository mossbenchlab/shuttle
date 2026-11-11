"""Shuttle schemas for the WB-1 task data (derived from the task generator's shapes)."""
SCHEMAS = {
 "inventory": "table items key sku : sku:kw name:str qty:int reorder:int price:dec updated:dt",
 "orders": "table orders key id : id:int placed:dt status:kw priority:int tags:list<kw>=[] lines:lines\ntable orders.lines : sku:kw qty:int unit_price:dec",
 "readings": "table readings key station,at : station:kw at:dt temp:dec humidity:dec ok:bool note:str?",
 "config": "doc service:str version:str debug:bool limits:map flags:list<kw>\ntable endpoints key path : path:str method:kw auth:bool rate:int burst:int",
 "course": "doc title:str term:kw year:int instructor:map\ntable students key id : id:int name:str score:dec grade:kw late:int absent:int",
}
