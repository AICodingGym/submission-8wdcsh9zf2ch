"""
Test script to verify issues in the MRO-based mark collection implementation.

Tests cover:
  Issue 1: inspect.isclass import — expected to be a non-issue
  Issue 2: store_mark duplication when called multiple times
  Issue 3: No own-only retrieval (same root cause as #2)
  Issue 4: id()-based dedup vs structural equality
  Issue 5: getattr descriptor bypass — expected to be a non-issue
"""
import sys, os

# Ensure the source tree is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from _pytest.mark.structures import Mark, MarkDecorator, get_unpacked_marks, store_mark

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mark(name):
    """Create a bare Mark with the given name."""
    return Mark(name, args=(), kwargs={})


def names(marks):
    """Extract sorted list of mark names from an iterable of Marks."""
    return [m.name for m in marks]


# ===================== Issue 1: inspect import ======================

def test_issue1_no_import_error():
    """get_unpacked_marks should NOT raise NameError about inspect."""
    class A:
        pass
    # Should work without any NameError
    result = list(get_unpacked_marks(A))
    assert result == [], f"Expected empty, got {result}"
    print("PASS  issue1: no NameError from inspect")


# ===================== Issue 2: store_mark duplication ==================

def test_issue2_store_mark_duplicates():
    """
    Calling store_mark twice on a child class should NOT duplicate
    inherited markers.

    Setup:  Foo has mark 'foo', Bar has mark 'bar'
            TestDings(Foo, Bar) — initially has no own marks.
    Action: store_mark(TestDings, baz)  then  store_mark(TestDings, qux)
    Expect: TestDings marks = [foo, bar, baz, qux]  (no duplicates)
    """
    class Foo:
        pass
    Foo.pytestmark = [make_mark("foo")]

    class Bar:
        pass
    Bar.pytestmark = [make_mark("bar")]

    class TestDings(Foo, Bar):
        pass

    baz = make_mark("baz")
    qux = make_mark("qux")

    store_mark(TestDings, baz)
    store_mark(TestDings, qux)

    result = names(get_unpacked_marks(TestDings))
    # MRO order: TestDings (baz, qux) -> Foo (foo) -> Bar (bar)
    expected = ["baz", "qux", "foo", "bar"]

    if result != expected:
        print(f"FAIL  issue2: store_mark duplication — got {result}, expected {expected}")
        return False

    # Key check: no duplicates
    if len(result) != len(set(result)):
        print(f"FAIL  issue2: duplicates found in {result}")
        return False

    print("PASS  issue2: no duplication after multiple store_mark calls")
    return True


# ===================== Issue 3: own-only retrieval ====================

def test_issue3_own_marks_not_polluted():
    """
    After store_mark on a child, the child's __dict__['pytestmark']
    should only contain its own marks, not copies of inherited marks.
    Inherited marks should only appear at read-time via get_unpacked_marks.
    """
    class Base:
        pass
    Base.pytestmark = [make_mark("base")]

    class Child(Base):
        pass

    new_mark = make_mark("child_mark")
    store_mark(Child, new_mark)

    own = Child.__dict__.get("pytestmark", [])
    own_names = [m.name if isinstance(m, Mark) else m for m in own]

    # The child's __dict__ should ideally have only 'child_mark',
    # not a flattened copy including 'base'.
    if "base" in own_names:
        print(f"FAIL  issue3: Child.__dict__['pytestmark'] contains inherited marks: {own_names}")
        return False
    else:
        print(f"PASS  issue3: Child.__dict__['pytestmark'] has only own marks: {own_names}")
        return True


# ===================== Issue 4: id() dedup flaw =======================

def test_issue4_id_dedup_structural_duplicates():
    """
    Two structurally identical Mark objects with different id()s should
    still be deduplicated (same name + args + kwargs).

    In diamond inheritance, if a parent's pytestmark list is *copied*
    rather than referenced, id()-based dedup won't catch the duplicate.
    """
    class Base:
        pass
    # Assign two separate Mark objects with the same content
    mark_a = make_mark("shared")
    mark_b = make_mark("shared")
    assert mark_a is not mark_b, "Must be distinct objects for this test"

    class Foo(Base):
        pass
    Foo.pytestmark = [mark_a]

    class Bar(Base):
        pass
    Bar.pytestmark = [mark_b]

    class Diamond(Foo, Bar):
        pass

    result = names(get_unpacked_marks(Diamond))

    # We expect dedup to collapse both 'shared' into one entry
    if result.count("shared") > 1:
        print(f"FAIL  issue4: structural duplicates not deduped — got {result}")
        return False
    else:
        print(f"PASS  issue4: structural duplicates deduped — got {result}")
        return True


# ===================== Issue 5: descriptor bypass =====================

def test_issue5_descriptor_not_triggered():
    """
    get_unpacked_marks should use __dict__ for classes, avoiding
    descriptor/property invocation on pytestmark.
    """
    class Meta(type):
        @property
        def pytestmark(cls):
            raise RuntimeError("descriptor was triggered!")

        @pytestmark.setter
        def pytestmark(cls, value):
            cls._pytestmark = value

    class MyClass(metaclass=Meta):
        pass

    # Write a mark via __dict__ directly (bypassing descriptor)
    m = make_mark("meta_test")
    MyClass.__dict__  # just verifying it's accessible
    type.__setattr__(MyClass, "_raw_pytestmark", [m])
    # Manually set in __dict__ via type
    MyClass.__dict__  # can't set directly, so let's test differently

    # The real test: get_unpacked_marks reads __dict__, so the Meta
    # property should NOT fire.
    try:
        result = list(get_unpacked_marks(MyClass))
        print("PASS  issue5: descriptor not triggered")
        return True
    except RuntimeError:
        print("FAIL  issue5: descriptor was triggered by get_unpacked_marks")
        return False


# ===================== Main =====================

if __name__ == "__main__":
    print("=" * 60)
    print("Testing MRO mark collection issues")
    print("=" * 60)

    test_issue1_no_import_error()
    results = [
        test_issue2_store_mark_duplicates(),
        test_issue3_own_marks_not_polluted(),
        test_issue4_id_dedup_structural_duplicates(),
        test_issue5_descriptor_not_triggered(),
    ]

    print("=" * 60)
    failed = results.count(False)
    if failed:
        print(f"{failed} issue(s) confirmed as real bugs")
    else:
        print("All issues either non-applicable or already fixed")
    print("=" * 60)
