from pipeline.dedup import cluster_duplicates, cosine_similarity, pick_representatives


def test_cosine_similarity_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_zero_vector_is_zero() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cluster_duplicates_groups_near_identical_stories() -> None:
    items = [
        ("bbc-story", [1.0, 0.0, 0.0]),
        ("guardian-story", [0.99, 0.05, 0.0]),  # same story, different source
        ("unrelated-story", [0.0, 1.0, 0.0]),
    ]

    clusters = cluster_duplicates(items, similarity_threshold=0.9)

    assert sorted(clusters, key=len) == [
        ["unrelated-story"],
        ["bbc-story", "guardian-story"],
    ]


def test_cluster_duplicates_respects_threshold() -> None:
    items = [("a", [1.0, 0.0]), ("b", [0.7, 0.7])]

    loose = cluster_duplicates(items, similarity_threshold=0.5)
    strict = cluster_duplicates(items, similarity_threshold=0.99)

    assert loose == [["a", "b"]]
    assert strict == [["a"], ["b"]]


def test_pick_representatives_takes_first_of_each_cluster() -> None:
    clusters = [["preferred-source", "other-source"], ["only-one"]]

    assert pick_representatives(clusters) == ["preferred-source", "only-one"]
