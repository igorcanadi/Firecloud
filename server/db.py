from collections import namedtuple
from time import time

Entry = namedtuple('Entry', ['key', 'ts', 'val'])

class Datastore(object):
  def __init__(self):
    self.db = {}

  def make_empty_entry(self, key):
    return Entry(key, 0, '[]')

  def put(self, ent):
    self[ent.key] = ent

  def __getitem__(self, ke):
    if ke not in self.db:
      return self.make_empty_entry(ke)
    return self.db[ke]

  def __setitem__(self, ke, val):
    print val
    assert type(val) == Entry
    if (ke not in self.db) or (self.db[ke].ts < val.ts):
      self.db[ke] = val
