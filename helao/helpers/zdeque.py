from collections import deque
import pyzstd
import pickle


class zdeque(deque):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __getitem__(self, i):
        x = super().__getitem__(i)
        return pickle.loads(pyzstd.decompress(x))

    def __iter__(self):
        for x in super().__iter__():
            yield pickle.loads(pyzstd.decompress(x))

    def popleft(self):
        x = super().popleft()
        return pickle.loads(pyzstd.decompress(x))

    def pop(self):
        x = super().pop()
        return pickle.loads(pyzstd.decompress(x))

    def insert(self, i, x):
        super().insert(i, pyzstd.compress(pickle.dumps(x)))

    def append(self, x):
        super().append(pyzstd.compress(pickle.dumps(x)))

    def appendleft(self, x):
        super().appendleft(pyzstd.compress(pickle.dumps(x)))

    def index(self, x):
        return super().index(pyzstd.compress(pickle.dumps(x)))
