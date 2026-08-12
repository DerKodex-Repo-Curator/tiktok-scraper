## `proxy-rotation` Specification

### Requirements

* MUST generate proxy URLs using `socks5h://<uuid4():dummy@proxyto.hs.sof.ar:9050`
* MUST rotate exit IP per retry via fresh GUID username
* MAY fallback to direct connection if proxyto endpoint fails (documented escape path)

### Scenarios

**GIVEN** a new download attempt
* WHEN `build_proxy_url(uuid4())` is called
* THEN returns valid `socks5h` proxy URL format

**GIVEN** 3 consecutive proxy failures
* WHEN `build_proxy_url()` is called
* THEN retries with new GUID up to 5 attempts

**GIVEN** proxyto endpoint outage
* WHEN build_proxy_url() fails
* THEN MAY use direct connection (per `doc_config_fallback` in docs)