const N: usize = 624;
const M: usize = 397;
const MATRIX_A: u32 = 0x9908_b0df;
const UPPER: u32 = 0x8000_0000;
const LOWER: u32 = 0x7fff_ffff;

pub struct Mt {
    mt: [u32; N],
    mti: usize,
}

impl Mt {
    pub fn from_state(words: &[u32], index: usize) -> Result<Self, String> {
        if words.len() < N {
            return Err(format!("MT19937 state needs {N} words, got {}", words.len()));
        }
        if index > N {
            return Err(format!("MT19937 state index {index} is past the {N}-word block"));
        }
        let mut mt = [0u32; N];
        mt.copy_from_slice(&words[..N]);
        Ok(Mt { mt, mti: index })
    }

    pub fn state(&self) -> (Vec<u32>, usize) {
        (self.mt.to_vec(), self.mti)
    }

    #[allow(dead_code)]
    pub fn init_genrand(s: u32) -> Self {
        let mut mt = [0u32; N];
        mt[0] = s;
        for i in 1..N {
            mt[i] = 1812433253u32
                .wrapping_mul(mt[i - 1] ^ (mt[i - 1] >> 30))
                .wrapping_add(i as u32);
        }
        Mt { mt, mti: N }
    }

    #[allow(dead_code)]
    pub fn init_by_array(key: &[u32]) -> Self {
        let mut r = Mt::init_genrand(19650218);
        let mut i = 1usize;
        let mut j = 0usize;
        let klen = key.len().max(1);
        let mut k = N.max(klen);
        while k > 0 {
            let prev = r.mt[i - 1] ^ (r.mt[i - 1] >> 30);
            r.mt[i] = (r.mt[i] ^ prev.wrapping_mul(1664525))
                .wrapping_add(if key.is_empty() { 0 } else { key[j] })
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                r.mt[0] = r.mt[N - 1];
                i = 1;
            }
            if j >= klen {
                j = 0;
            }
            k -= 1;
        }
        k = N - 1;
        while k > 0 {
            let prev = r.mt[i - 1] ^ (r.mt[i - 1] >> 30);
            r.mt[i] = (r.mt[i] ^ prev.wrapping_mul(1566083941)).wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                r.mt[0] = r.mt[N - 1];
                i = 1;
            }
            k -= 1;
        }
        r.mt[0] = 0x8000_0000;
        r.mti = N;
        r
    }

    #[inline]
    pub fn genrand_u32(&mut self) -> u32 {
        if self.mti >= N {
            let mt = &mut self.mt;
            let mag01 = |y: u32| if y & 1 == 1 { MATRIX_A } else { 0 };
            for kk in 0..(N - M) {
                let y = (mt[kk] & UPPER) | (mt[kk + 1] & LOWER);
                mt[kk] = mt[kk + M] ^ (y >> 1) ^ mag01(y);
            }
            for kk in (N - M)..(N - 1) {
                let y = (mt[kk] & UPPER) | (mt[kk + 1] & LOWER);
                mt[kk] = mt[kk + M - N] ^ (y >> 1) ^ mag01(y);
            }
            let y = (mt[N - 1] & UPPER) | (mt[0] & LOWER);
            mt[N - 1] = mt[M - 1] ^ (y >> 1) ^ mag01(y);
            self.mti = 0;
        }
        let mut y = self.mt[self.mti];
        self.mti += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^= y >> 18;
        y
    }

    #[inline]
    pub fn random(&mut self) -> f64 {
        let a = (self.genrand_u32() >> 5) as f64;
        let b = (self.genrand_u32() >> 6) as f64;
        (a * 67108864.0 + b) * (1.0 / 9007199254740992.0)
    }

    #[inline]
    pub fn getrandbits(&mut self, k: u32) -> u128 {
        if k <= 32 {
            return (self.genrand_u32() >> (32 - k)) as u128;
        }
        let mut result: u128 = 0;
        let mut remaining = k;
        let mut shift = 0u32;
        while remaining > 0 {
            let mut r = self.genrand_u32();
            if remaining < 32 {
                r >>= 32 - remaining;
            }
            result |= (r as u128) << shift;
            shift += 32;
            remaining = remaining.saturating_sub(32);
        }
        result
    }

    #[inline]
    pub fn randbelow(&mut self, n: u128) -> u128 {
        if n == 0 {
            return 0;
        }
        let k = 128 - n.leading_zeros();
        let mut r = self.getrandbits(k);
        while r >= n {
            r = self.getrandbits(k);
        }
        r
    }

    #[inline]
    pub fn randrange(&mut self, n: usize) -> usize {
        self.randbelow(n as u128) as usize
    }
}
