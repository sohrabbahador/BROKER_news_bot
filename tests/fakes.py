"""دیتابیس و بله‌ی مجازی برای تست کامل مسیرها بدون شبکه."""
import copy, itertools, types

class DuplicateKeyError(Exception):
    pass

def _match(doc, flt):
    for k, v in (flt or {}).items():
        val = doc.get(k)
        if isinstance(v, dict) and v and all(str(x).startswith("$") for x in v):
            for op, arg in v.items():
                if op == "$gt" and not (val is not None and val > arg): return False
                if op == "$gte" and not (val is not None and val >= arg): return False
                if op == "$lt" and not (val is not None and val < arg): return False
                if op == "$lte" and not (val is not None and val <= arg): return False
                if op == "$ne" and val == arg: return False
                if op == "$in" and val not in arg: return False
                if op == "$exists" and (k in doc) != bool(arg): return False
        elif val != v:
            return False
    return True

def _apply(doc, update):
    for k, v in update.get("$set", {}).items(): doc[k] = v
    for k, v in update.get("$inc", {}).items(): doc[k] = doc.get(k, 0) + v
    for k in update.get("$unset", {}): doc.pop(k, None)

class Cursor(list):
    def sort(self, *a, **k): return self
    def limit(self, n): return Cursor(self[:n])

class Col:
    _auto = itertools.count(1)
    def __init__(self): self.docs = {}
    def _m(self, flt): return [d for d in self.docs.values() if _match(d, flt)]
    def find_one(self, flt=None, projection=None):
        m = self._m(flt); return copy.deepcopy(m[0]) if m else None
    def find(self, flt=None, projection=None): return Cursor(copy.deepcopy(self._m(flt)))
    def insert_one(self, doc):
        doc = copy.deepcopy(doc); doc.setdefault("_id", next(Col._auto))
        if doc["_id"] in self.docs: raise DuplicateKeyError(doc["_id"])
        self.docs[doc["_id"]] = doc
    def _upsert_doc(self, flt, update):
        doc = {k: v for k, v in (flt or {}).items() if not (isinstance(v, dict) and any(str(x).startswith("$") for x in v))}
        doc.setdefault("_id", next(Col._auto)); _apply(doc, update); self.docs[doc["_id"]] = doc; return doc
    def update_one(self, flt, update, upsert=False):
        m = self._m(flt)
        if m: _apply(m[0], update); return types.SimpleNamespace(matched_count=1)
        if upsert: self._upsert_doc(flt, update)
        return types.SimpleNamespace(matched_count=0)
    def find_one_and_update(self, flt, update, upsert=False, return_document=False):
        m = self._m(flt)
        if m:
            before = copy.deepcopy(m[0]); _apply(m[0], update)
            return copy.deepcopy(m[0]) if return_document else before
        if upsert:
            doc = self._upsert_doc(flt, update); return copy.deepcopy(doc) if return_document else None
        return None
    def find_one_and_delete(self, flt):
        m = self._m(flt)
        if m: return copy.deepcopy(self.docs.pop(m[0]["_id"]))
    def delete_one(self, flt):
        m = self._m(flt)
        if m: self.docs.pop(m[0]["_id"])
    def count_documents(self, flt=None): return len(self._m(flt))

class FakeDB:
    def __init__(self): self._c = {}
    def __getattr__(self, name):
        if name.startswith("_"): raise AttributeError(name)
        return self._c.setdefault(name, Col())
    def command(self, *a, **k): return {"ok": 1}

class FakeBale(types.ModuleType):
    """جای ماژول bale: هر فراخوانی را ثبت می‌کند."""
    def __init__(self):
        super().__init__("bale"); self.calls = []; self._mid = itertools.count(100); self.fail_next_publish = False
    def reset(self): self.calls.clear()
    def of(self, kind, chat=None): return [c for c in self.calls if c[0] == kind and (chat is None or c[1] == chat)]
    async def call(self, method, **p):
        self.calls.append(("call", method, p)); return {"ok": True, "result": {}}
    async def send_message(self, chat_id, text, keyboard=None, reply_keyboard=None):
        self.calls.append(("send_message", chat_id, text, keyboard, reply_keyboard))
        if self.fail_next_publish and str(chat_id).startswith("@"):
            self.fail_next_publish = False; return {"ok": False, "description": "boom"}
        return {"ok": True, "result": {"message_id": next(self._mid)}}
    async def send_photo(self, chat_id, png, caption="", keyboard=None):
        self.calls.append(("send_photo", chat_id, caption, keyboard)); return {"ok": True, "result": {"message_id": next(self._mid)}}
    async def edit_message_keyboard(self, chat_id, message_id, keyboard=None):
        self.calls.append(("edit_kb", chat_id, message_id, keyboard)); return {"ok": True}
    async def answer_callback(self, cb_id, text=""):
        self.calls.append(("answer", cb_id, text)); return {"ok": True}
    async def get_updates(self, offset=None, timeout=30):
        return {"ok": True, "result": []}
