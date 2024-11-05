from collections import deque
import pyzstd
import pickle


class zdeque(deque):
    """
    A subclass of `collections.deque` that compresses and decompresses items using `pyzstd` and `pickle`.

    Methods:
        __init__(*args, **kwargs):
            Initialize the zdeque object.

        __getitem__(i):
            Retrieve the item at index `i` after decompressing and unpickling it.

        __iter__():
            Iterate over the items, decompressing and unpickling each one.

        popleft():
            Remove and return the leftmost item after decompressing and unpickling it.

        pop():
            Remove and return the rightmost item after decompressing and unpickling it.

        insert(i, x):
            Insert item `x` at index `i` after pickling and compressing it.

        append(x):
            Append item `x` to the right end after pickling and compressing it.

        appendleft(x):
            Append item `x` to the left end after pickling and compressing it.

        index(x):
            Return the index of item `x` after pickling and compressing it.
    """
    def __init__(self, *args, **kwargs):
        """
        Initialize a new instance of the class.

        Parameters:
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.
        """
        super().__init__(*args, **kwargs)

    def __getitem__(self, i):
        """
        Retrieve an item from the deque, decompress and deserialize it.

        Args:
            i (int): The index of the item to retrieve.

        Returns:
            object: The decompressed and deserialized item at the specified index.
        """
        x = super().__getitem__(i)
        return pickle.loads(pyzstd.decompress(x))

    def __iter__(self):
        """
        Iterate over the elements in the deque, decompressing and unpickling each element.

        Yields:
            Any: The decompressed and unpickled element from the deque.
        """
        for x in super().__iter__():
            yield pickle.loads(pyzstd.decompress(x))

    def popleft(self):
        """
        Remove and return an object from the left end of the deque.

        This method overrides the `popleft` method of the superclass to 
        decompress and deserialize the object using `pyzstd` and `pickle`.

        Returns:
            Any: The decompressed and deserialized object from the left end of the deque.
        """
        x = super().popleft()
        return pickle.loads(pyzstd.decompress(x))

    def pop(self):
        """
        Remove and return an object from the deque.

        This method overrides the default `pop` method to decompress and 
        deserialize the object using `pyzstd` and `pickle` before returning it.

        Returns:
            Any: The decompressed and deserialized object from the deque.
        """
        x = super().pop()
        return pickle.loads(pyzstd.decompress(x))

    def insert(self, i, x):
        """
        Inserts an element at a given position in the deque.

        Args:
            i (int): The index at which the element should be inserted.
            x (Any): The element to be inserted. It will be serialized and compressed before insertion.

        Returns:
            None
        """
        super().insert(i, pyzstd.compress(pickle.dumps(x)))

    def append(self, x):
        """
        Append an item to the deque after compressing and serializing it.

        Args:
            x: The item to be appended to the deque. It will be serialized using
               `pickle` and then compressed using `pyzstd` before being appended.
        """
        super().append(pyzstd.compress(pickle.dumps(x)))

    def appendleft(self, x):
        """
        Add an element to the left end of the deque after compressing and serializing it.

        Args:
            x: The element to be added to the left end of the deque. The element will be
               serialized using pickle and then compressed using pyzstd before being added.
        """
        super().appendleft(pyzstd.compress(pickle.dumps(x)))

    def index(self, x):
        """
        Returns the index of the first occurrence of the specified element in the deque.

        Args:
            x: The element to search for in the deque. The element will be serialized
               using pickle and compressed using pyzstd before searching.

        Returns:
            int: The index of the first occurrence of the specified element.

        Raises:
            ValueError: If the element is not present in the deque.
        """
        return super().index(pyzstd.compress(pickle.dumps(x)))
