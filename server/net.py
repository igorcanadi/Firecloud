import cPickle as pickle
import socket
from collections import namedtuple
import tx
import re
import db
import time
import random

Packet = namedtuple('Packet', ['entry', 'is_master', 'type', 'orig', 'seq'])

TYPE_PUT = 'P'
TYPE_PACK = 'A'
TYPE_GET = 'G'
TYPE_GACK = 'H'

def check(txs):
  while True:
    keys = txs.keys()
    for key in keys:
      t = txs[key]
      if t.state == tx.DEAD:
        del txs[key]
      elif t.state == tx.ZOMBIE:
        if t.zombie_out(): 
          del txs[key]
          yield t;
      elif t.timed_out():
        del txs[key]
    yield None

class Network(object):
  def __init__(self, db, addrs, me, master):
    self.master = master
    self.me = me
    self.db = db
    self.txs = {}
    self.listeners = {}
    self.seen = set()
    self.get = re.compile("GET (\[.*?\]) (\[.*?\])")
    self.put = re.compile("PUT (\[.*?\]) (\[.*?\]) (\[.*?\])")
    self.last_zombie = time.time()

    addrs.remove(me)
    self.addrs = addrs
    self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ###print 'I AM:', me
    self.s.bind(me)
    self.next_zombie = check(self.txs)

  def __flood(self, orig, data):
    for a in filter(lambda x: x != orig, self.addrs):
      self.s.sendto(data, a)

  def make_ack(self, t, entry, seq):
    assert type(entry.key) is str
    return Packet(entry, self.master, t, self.me, seq)

  def flood(self, pkt):
    assert type(pkt.entry.key) is str
    ##print 'Floading: ', pkt
    self.__flood(None, pickle.dumps(pkt))

  def has_seen(self, pkt):
    return (pkt.entry.key, pkt.entry.ts, pkt.seq, pkt.orig) in self.seen

  def commit(self, tx):
    ##print 'Commit: ', tx.entry
    try:
      ##print self.listeners
      self.listeners[tx.seq].commit(tx) 
      del self.listeners[tx.seq]
    except KeyError:
      ##print 'Didnt find: ', (tx.seq)
      pass

  def see(self, pkt):
    self.seen.add((pkt.entry.key, pkt.entry.ts, pkt.seq, pkt.orig))

  def dispatch(self, entry, seq, typ, m):
    assert type(entry.key) is str

    if typ == TYPE_GACK:
      self.db.put(entry)
      # don't make a tx for it
      try:
        self.txs[seq].ack(entry, m)
      except KeyError:
        pass

    elif typ == TYPE_GET:
      self.flood(self.make_ack(TYPE_GACK, self.db[entry.key], seq))
    elif typ == TYPE_PUT:
      try:
        t = self.txs[seq]
      except KeyError:
        t = tx.Tx(self, seq)
        self.txs[seq] = t

      ##print '>>>>>> SETTING UPDATE TO:', entry, t
      t.update = entry
      t.ack(self.db[entry.key], m)
      a = self.make_ack(TYPE_PACK, self.db[entry.key], seq)
      self.flood(a)
      ##print t

    elif typ == TYPE_PACK:
      try:
        t = self.txs[seq]
      except KeyError:
        t = tx.Tx(self, seq)
        self.txs[seq] = t

      t.ack(entry, m)

  def clientDispatch(self, data, addr):
    ##print data
    if data[0] == 'G':
      m = self.get.match(data)
      key = m.group(1)
      ##print 'Matched to: key: ', key
      opaque = m.group(2)
      value = None
      type_ = TYPE_GET
    else:
      m = self.put.match(data)
      key = m.group(1)
      value = m.group(2)
      ##print 'Matched to: value: ', value
      opaque = m.group(3)
      type_ = TYPE_PUT

    ti = time.time()
    r = random.random()
    ##print key
    assert type(key) is str
    e = db.Entry(key, ti, value if type_ == TYPE_PUT else self.db[key].val)
    self.listeners[r] = tx.Listener(self.db, opaque, self.s, addr)
    if type_ == TYPE_GET:
      t = tx.Tx(self, r)
      self.txs[r] = t
      t.ack(e, self.master)


    ##print self.db[key]
    assert type(e.key) is str
    pkt = pickle.dumps(Packet(e, self.master, type_, self.me, r))
    self.s.sendto(pkt, self.me)

  def rebroadcast(self, tx):
    a = self.make_ack(TYPE_PACK, tx.entry, tx.seq)
    self.flood(a)

  def poll(self):
    while True:
      if time.time() > self.last_zombie + 1: 
        self.last_zombie = time.time()
        zombie = next(self.next_zombie)
        if  zombie is not None:
          self.rebroadcast(zombie)


      (data, addr) = self.s.recvfrom(10000)

      if data[0:3] == 'GET' or data[0:3] == 'PUT':
        self.clientDispatch(data, addr)
      else:
        pkt = pickle.loads(data)
        if self.has_seen(pkt): 
          continue

        ##print pkt
        self.see(pkt)
        self.dispatch(pkt.entry, pkt.seq, pkt.type, pkt.is_master)
        assert type(pkt.entry.key) is str
        self.__flood(addr, data)
