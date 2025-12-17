class Comb:
    """\
    nCr % mod を計算する.  
    """

    _limit: int
    _mod: int

    _fac: list[int]
    _inv: list[int]
    _facinv: list[int]

    def __init__(self, limit=10**6, mod=998244353):
        """\
        nCr % mod を計算するための前計算.  
        計算量 O(limit).

        Args:
            limit (int?): nCr を計算するときの n の最大値.
            mod (prime?): mod で割った余り. 素数.
        """
        self._limit = limit
        self._mod = mod

        self._fac = [1] * (limit + 1)
        self._inv = [1] * (limit + 1)
        self._facinv = [1] * (limit + 1)

        for i in range(2, limit + 1):
            self._fac[i] = self._fac[i - 1] * i % mod
            self._inv[i] = (mod - self._inv[mod % i] * (mod // i)) % mod
            self._facinv[i] = self._facinv[i - 1] * self._inv[i] % mod

    def __call__(self, n: int, r: int) -> int:
        """\
        nCr % mod を計算する.
        クエリ O(1).

        Args:
            n (int): nCr を計算するときの n.
            r (int): nCr を計算するときの r.
        
        Returns:
            nCr % mod の結果.
        """
        assert (
            0 <= n <= self._limit
        ), f"n は 0 以上 {self._limit} である必要があります.: {n=}"

        if n < r:
            return 0

        return (
            self._fac[n] * self._facinv[n - r] % self._mod * self._facinv[r] % self._mod
        )
