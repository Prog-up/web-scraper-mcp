# Dependency advisory inventory

Queried OSV on 5 October 2026 for 130 third-party packages in the frozen lockfile. GHSA/PYSEC aliases are deduplicated into 24 GHSA records across five packages. These are version matches; see the review for application applicability. Runtime includes requested extras.

| Package / locked version | Runtime | Upstream severity | Advisory | Reported fixed version | Summary |
|---|---|---|---|---|---|
| anyio 4.14.1 | Yes | HIGH | [GHSA-3w57-8xmc-8v26](https://github.com/agronholm/anyio/security/advisories/GHSA-3w57-8xmc-8v26) | 4.14.2 | AnyIO run_process/open_process ignores extra_groups and can retain parent supplementary groups |
| anyio 4.14.1 | Yes | MODERATE | [GHSA-5p39-cfhj-2xmp](https://github.com/agronholm/anyio/security/advisories/GHSA-5p39-cfhj-2xmp) | 4.14.2 | AnyIO process-pool workers can block indefinitely on undrained stderr |
| anyio 4.14.1 | Yes | CRITICAL | [GHSA-82r6-8w77-94w6](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6) | 4.14.2 | AnyIO: TLSStream IDNA 2003 host name encoding enables potential TLS certificate spoofing |
| h2 4.3.0 | Yes | MODERATE | [GHSA-6hr6-w5qg-qmwg](https://github.com/python-hyper/h2/security/advisories/GHSA-6hr6-w5qg-qmwg) | 4.4.1 | h2: Duplicate Host header could facilitate request smuggling |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-2gx3-rcp4-g85q](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-2gx3-rcp4-g85q) | 2.14.0 | PyJWT: PyJWKClient still amplifies unauthenticated JWKS fetches on unknown kid values (incomplete fix of CVE-2026-48524) |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-42vr-xj54-vc7v](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-42vr-xj54-vc7v) | 2.15.0 | PyJWT: Unauthenticated RecursionError DoS in pre-verification payload parse (PyJWKClient.get_signing_key_from_jwt / verify_signature=False) |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-8wjv-2p76-3863](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-8wjv-2p76-3863) | 2.14.0 | PyJWT: Uncaught RecursionError in jwt.decode() on deeply nested token header |
| pyjwt 2.13.0 | Yes | HIGH | [GHSA-9j54-fg26-wv3r](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9j54-fg26-wv3r) | 2.14.0 | PyJWT: PyJWK accepts empty HMAC keys, bypassing PyJWT's empty-key validation |
| pyjwt 2.13.0 | Yes | HIGH | [GHSA-9v7f-9g4p-ffgj](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-9v7f-9g4p-ffgj) | 2.14.0 | PyJWT: PyJWKClient follows redirects when fetching JWKS |
| pyjwt 2.13.0 | Yes | CRITICAL | [GHSA-ffc3-869f-jxw9](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9) | 2.14.0 | PyJWT: Asymmetric-PEM detection bypass: whitespace/line-ending-mutated public keys skip the HS/asymmetric confusion guard |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-gvp8-978c-rx2q](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q) | No fixed release declared | PyJWT.decode() reintroduces options-dict mutation, enabling silent claim-verification bypass on dict reuse |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-hxm8-2xgr-2p9m](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-hxm8-2xgr-2p9m) | 2.14.0 | PyJWT: Non-canonical signature segments enable raw-token revocation bypass |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-jwrc-g2q2-pq5p](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-jwrc-g2q2-pq5p) | 2.14.0 | PyJWT: ReDoS vulnerability when calling the `is_pem_format` function. |
| pyjwt 2.13.0 | Yes | HIGH | [GHSA-p4g4-x82p-q773](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-p4g4-x82p-q773) | 2.14.0 | PyJWT: Public keys in DER form are accepted as HMAC secrets, bypassing the CVE-2022-29217 guard |
| pyjwt 2.13.0 | Yes | HIGH | [GHSA-r6x4-923q-g947](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-r6x4-923q-g947) | 2.14.0 | PyJWT BOM Bypass |
| pyjwt 2.13.0 | Yes | HIGH | [GHSA-w2cx-738m-mc7w](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-w2cx-738m-mc7w) | 2.14.0 | PyJWT accepts public JWK containers as HMAC secrets |
| pyjwt 2.13.0 | Yes | MODERATE | [GHSA-w6j9-cwv2-h6wq](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-w6j9-cwv2-h6wq) | 2.14.0 | PyJWT: Malformed RSA JWK aborts parsing of an entire JWK Set |
| urllib3 2.7.0 | Yes | HIGH | [GHSA-8988-9cw3-xx77](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77) | 2.8.0 | urllib3: HTTPS proxy TLS configuration may be ignored or overridden |
| urllib3 2.7.0 | Yes | MODERATE | [GHSA-gh4c-6fx4-qh6g](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g) | 2.8.0 | urllib3: Chunked Deflate streaming can enter an infinite loop |
| urllib3 2.7.0 | Yes | HIGH | [GHSA-vxq7-64xx-v4gw](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) | 2.8.0 | urllib3: HTTPResponse.stream()/read_chunked() buffers an unbounded chunk-size line into memory |
| virtualenv 21.5.1 | Dev only | HIGH | [GHSA-94p9-xgh2-xp45](https://github.com/pypa/virtualenv/security/advisories/GHSA-94p9-xgh2-xp45) | 21.7.12 | virtualenv: Downloaded seed wheels (pip/setuptools) are not integrity-checked before use |
| virtualenv 21.5.1 | Dev only | MODERATE | [GHSA-9h9j-4vrj-gf7g](https://github.com/pypa/virtualenv/security/advisories/GHSA-9h9j-4vrj-gf7g) | 21.7.11 | virtualenv writes prompt values into pyvenv.cfg without sanitizing line boundaries, allowing configuration injection |
| virtualenv 21.5.1 | Dev only | HIGH | [GHSA-p58f-9548-mpm2](https://github.com/pypa/virtualenv/security/advisories/GHSA-p58f-9548-mpm2) | 21.7.13 | virtualenv bash and fish activation scripts execute commands embedded in paths |
| virtualenv 21.5.1 | Dev only | HIGH | [GHSA-x78j-v8h9-3j2q](https://github.com/pypa/virtualenv/security/advisories/GHSA-x78j-v8h9-3j2q) | 21.7.12 | virtualenv: Command injection via --prompt in activate.bat (batch activator) |

The PyJWT options-mutation record declares a last-affected version without an explicit fixed event. Re-query after upgrading. The existing August Trivy report describes a different OS/image and is not evidence of the current Docker build.
