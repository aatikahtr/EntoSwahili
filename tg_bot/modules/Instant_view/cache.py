import time
from collections import OrderedDict

class LRUCache:
    def __init__(self, max_size=100, ttl=1800):
        """
        max_size = idadi max ya links
        ttl = muda wa kuishi (seconds)
        """
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key):
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]

        # TTL expired
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None

        # move to recent
        self.cache.move_to_end(key)
        return value

    def set(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)

        self.cache[key] = (value, time.time())

        # LRU eviction
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)
