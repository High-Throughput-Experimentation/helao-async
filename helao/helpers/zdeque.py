from collections import deque
import zlib
import pickle


class zdeque(deque):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __getitem__(self, i):
        x = super().__getitem__(i)
        return pickle.loads(zlib.decompress(x))

    def __iter__(self):
        for x in super().__iter__():
            yield pickle.loads(zlib.decompress(x))

    def popleft(self):
        x = super().popleft()
        return pickle.loads(zlib.decompress(x))

    def pop(self):
        x = super().pop()
        return pickle.loads(zlib.decompress(x))

    def insert(self, i, x):
        super().insert(i, zlib.compress(pickle.dumps(x)))

    def append(self, x):
        super().append(zlib.compress(pickle.dumps(x)))

    def appendleft(self, x):
        super().appendleft(zlib.compress(pickle.dumps(x)))

    def index(self, x):
        return super().index(zlib.compress(pickle.dumps(x)))
