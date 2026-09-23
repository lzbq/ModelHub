import unittest

from memory.conversation_memory import MemoryManager, MsgRole


class FakePipeline:
    def __init__(self, store):
        self.store = store
        self.in_multi = False
        self.operations = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def watch(self, *keys):
        return None

    def unwatch(self):
        return None

    def lrange(self, key, start, end):
        return self.store.lrange(key, start, end)

    def get(self, key):
        return self.store.values.get(key)

    def multi(self):
        self.in_multi = True

    def _queue(self, name, *args):
        self.operations.append((name, args))
        return self

    def delete(self, key):
        return self._queue("delete", key)

    def rpush(self, key, *values):
        return self._queue("rpush", key, *values)

    def ltrim(self, key, start, end):
        return self._queue("ltrim", key, start, end)

    def expire(self, key, seconds):
        return self._queue("expire", key, seconds)

    def setex(self, key, seconds, value):
        return self._queue("setex", key, seconds, value)

    def execute(self):
        for name, args in self.operations:
            if name == "delete":
                self.store.lists.pop(args[0], None)
            elif name == "rpush":
                self.store.lists.setdefault(args[0], []).extend(args[1:])
            elif name == "ltrim":
                self.store.lists[args[0]] = self.store.lists.get(args[0], [])[args[1]:args[2] + 1]
            elif name == "setex":
                self.store.values[args[0]] = args[2]
            elif name == "expire":
                pass
        return []


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.values = {}

    def pipeline(self):
        return FakePipeline(self)

    def lrange(self, key, start, end):
        values = list(self.lists.get(key, []))
        if end == -1:
            return values[start:]
        return values[start:end + 1]

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def expire(self, key, seconds):
        return True

    def llen(self, key):
        return len(self.lists.get(key, []))


class MemoryCompressionConcurrencyTests(unittest.TestCase):

    def test_compression_preserves_messages_pushed_after_snapshot(self):
        manager = MemoryManager.__new__(MemoryManager)
        manager._redis = FakeRedis()
        key = "wm:u:c"
        summary_key = "summary:u:c"
        snapshot = [f"old-{index}" for index in range(14, -1, -1)]
        manager._redis.lists[key] = ["new-2", "new-1", *snapshot]
        manager._redis.values[summary_key] = "previous"

        committed = manager._commit_compression(key, summary_key, snapshot, "next")

        self.assertTrue(committed)
        self.assertEqual(["new-2", "new-1", *snapshot[:5]], manager._redis.lists[key])
        self.assertEqual("previous\nnext", manager._redis.values[summary_key])

    def test_compression_fails_closed_when_snapshot_suffix_changed(self):
        manager = MemoryManager.__new__(MemoryManager)
        manager._redis = FakeRedis()
        key = "wm:u:c"
        snapshot = ["three", "two", "one"]
        manager._redis.lists[key] = ["new", "changed", "two", "one"]

        committed = manager._commit_compression(key, "summary:u:c", snapshot, "summary")

        self.assertFalse(committed)
        self.assertEqual(["new", "changed", "two", "one"], manager._redis.lists[key])

    def test_redis_key_components_escape_delimiters(self):
        key_a = MemoryManager._wm_key("a:b", "c")
        key_b = MemoryManager._wm_key("a", "b:c")

        self.assertNotEqual(key_a, key_b)
        self.assertEqual("wm:a%3Ab:c", key_a)
        self.assertEqual("wm:a:b%3Ac", key_b)
        self.assertNotEqual(
            MemoryManager._wm_key("%3A", "c"),
            MemoryManager._wm_key(":", "c"),
        )


class MemoryAuditIsolationTests(unittest.IsolatedAsyncioTestCase):

    async def test_eval_message_keeps_redis_but_skips_pg_and_compression(self):
        manager = MemoryManager.__new__(MemoryManager)
        manager._redis = FakeRedis()
        manager._pg_store = type("FakePg", (), {"calls": []})()

        async def pg_add_message(*args, **kwargs):
            manager._pg_store.calls.append((args, kwargs))

        manager._pg_store.add_message = pg_add_message
        compress_calls = []

        async def compress(user_id, conv_id):
            compress_calls.append((user_id, conv_id))

        manager._compress = compress
        key = manager._wm_key("eval-user", "eval-conv")
        manager._redis.lists[key] = ["old"] * manager.COMPRESS_AT

        await manager.add_message(
            "eval-user",
            "eval-conv",
            MsgRole.USER,
            "evaluation turn",
            persist_audit=False,
        )

        self.assertEqual(manager.COMPRESS_AT + 1, manager._redis.llen(key))
        self.assertEqual([], manager._pg_store.calls)
        self.assertEqual([], compress_calls)


if __name__ == "__main__":
    unittest.main()
