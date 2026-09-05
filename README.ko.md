[English](README.md) | **한국어**

# xdgkit

파이썬을 위한 안전한 XDG 스타일 애플리케이션 저장소: 경로, 자격증명, 권한, 런타임 파일.

모든 커맨드라인 앱이 디스크에서 해야 하는 두 가지 — **파일이 어디 있는지 찾기**와
**시크릿(비밀값)을 해석하기** — 를 모든 OS에서 똑같은 방식으로 한 번에 처리하는, 작고
의존성 없는 기반입니다.

- **디렉터리**는 [XDG Base Directory 명세](https://specifications.freedesktop.org/basedir/latest/)
  (`config` / `data` / `state` / `cache` / `runtime`)를 따르며, 모든 플랫폼에서 `~/.config`
  레이아웃을 사용합니다 — git, ssh, aws가 이미 따르는 관례라 머신마다 경로가 동일하고
  별도의 플랫폼 라이브러리가 필요 없습니다.
- **시크릿**은 정해진 순서로 해석됩니다 — 명시적 값, 그다음 환경변수, 그다음 공유
  스토어, 마지막으로 앱 자신의 스토어 — 그래서 여러 앱이 공통으로 쓰는 키를 각 앱에
  복사하지 않고 **한 곳**에 둘 수 있습니다.
- **저장**은 기본적으로 0700 디렉터리 안의 mode 0600 `credentials.json` 평문 파일입니다
  (헤드리스 환경과 여러 머신에서 신뢰할 수 있음). OS 키링(keyring)은 파일 자동 폴백이
  딸린 opt-in 백엔드입니다.

## 설치

```sh
pip install xdgkit            # 파일 스토어, 런타임 의존성 0
pip install "xdgkit[keyring]" # 선택적 OS 키링 백엔드 추가
```

Python 3.11+ 필요.

## 디렉터리

```python
from xdgkit import config_dir, data_dir, state_dir, cache_dir, runtime_dir

config_dir("myapp")   # ~/.config/myapp        (또는 $XDG_CONFIG_HOME/...)
data_dir("myapp")     # ~/.local/share/myapp   (또는 $XDG_DATA_HOME/...)
state_dir("myapp")    # ~/.local/state/myapp   (또는 $XDG_STATE_HOME/...)
cache_dir("myapp")    # ~/.cache/myapp         (또는 $XDG_CACHE_HOME/...)
runtime_dir("myapp")  # $XDG_RUNTIME_DIR/myapp, 없으면 보안된 0700 임시 디렉터리
```

앱 이름은 단일 경로 세그먼트(path segment, 슬래시 없는 한 조각)로 검증되므로, 조작된
이름이라도 자기 베이스 밖으로 벗어날 수 없습니다. `data_dir`와 `state_dir`는 앱별
`<APP>_DATA_DIR` / `<APP>_STATE_DIR` 환경변수 override(절대경로를 그대로 사용)도
존중하므로, 큰 아카이브를 아무것도 수정하지 않고 다른 볼륨으로 옮길 수 있습니다.
`runtime_dir`는 기본값이 명세에 정의되지 않은 유일한 XDG 디렉터리입니다. `XDG_RUNTIME_DIR`가
설정되지 않았을 때(cron, 컨테이너, macOS, Windows) 명세가 지시하는 대로 시스템 임시
디렉터리 아래에 uid로 키가 매겨진 비공개 디렉터리를 만들어 보안한 뒤 반환합니다
(`create=False`를 넘기면 생성 없이 경로만 계산).

## 시크릿

```python
from xdgkit import Credentials, secret, require, set_secret, unset_secret, secret_names

# 해석 순서: override > 환경변수 > 공유 스토어 > 이 앱의 스토어.
creds = Credentials("myapp", shared=["auth"])
key = creds.require("API_KEY")          # $API_KEY, 그다음 auth 스토어, 그다음 myapp 스토어; 없으면 예외
maybe = creds.secret("API_KEY")         # 같은 해석, 단 없으면 예외 대신 None 반환
creds.set("API_KEY", value="sk-...")    # myapp 자신의 스토어에 기록 (value는 키워드 전용)
creds.unset("API_KEY")
creds.names()                           # ["API_KEY", ...] -- 이름만, 값은 절대 반환하지 않음

# 모듈 수준 원샷 편의 함수 (각각 내부에서 Credentials를 구성):
secret("myapp", "API_KEY")                       # -> str | None
require("myapp", "API_KEY")                       # -> str, 없으면 CredentialsError
set_secret("myapp", "API_KEY", value="sk-...")   # value는 키워드 전용
unset_secret("myapp", "API_KEY")
secret_names("myapp")                             # -> list[str]
```

**공유 스토어**는 여러 앱이 공통으로 쓰는 키의 중복을 없애는 방법입니다. 공유 앱(예:
`"auth"`) 하나에 한 번 저장하면, 모든 소비자가 `shared=["auth"]`로 그 키를 해석합니다. 한
앱에만 특정한 키는 그 앱 자신의 스토어에 남습니다.

## `xdgkit` 명령

각 패키지마다 다른 키 저장 방식을 익힐 필요 없이, 어떤 앱의 시크릿이든 한 곳에서 한
형식으로 관리합니다:

```sh
xdgkit set myapp API_KEY               # 에코 없이 입력받아 credentials.json(0600)에 기록
xdgkit set myapp API_KEY --value sk-…  # 직접 전달도 가능(argv에 노출되니 입력 프롬프트 권장)
xdgkit list myapp                      # 이름만, 값은 절대 안 보임
xdgkit get myapp API_KEY               # 마스킹(sk***ef); 저장된 값만 읽음
xdgkit get myapp API_KEY --reveal      # 전체 출력
xdgkit get myapp API_KEY --resolve     # 저장된 값뿐 아니라 환경변수도 함께 참조
xdgkit unset myapp API_KEY
xdgkit path myapp                      # credentials.json 경로 출력
xdgkit dirs myapp                      # 다섯 디렉터리 모두 출력
xdgkit doctor                          # 모든 앱의 자격증명 파일/디렉터리 권한 점검
xdgkit doctor myapp other-app          # 지정한 앱만 점검
```

`set`, `get`, `list`, `unset`은 `--keyring`을 받아 OS 키링 백엔드로 동작합니다(파일 자동
폴백 포함). 종료 코드: `0` 성공, `1` 런타임 오류, `2` 사용법 오류(잘못된 앱 이름).

## 키링

파일 스토어가 기본인 이유는 어디서나 신뢰할 수 있기 때문입니다 — 헤드리스 서버, cron,
컨테이너, 여러 머신. OS 키링은 opt-in입니다:

```python
from xdgkit.backends import FileBackend, KeyringBackend, default_backend
from xdgkit import Credentials

backend = KeyringBackend(fallback=FileBackend())   # 데스크톱에선 키링, 서버에선 파일
creds = Credentials("myapp", backend=backend)
# 또는: default_backend(use_keyring=True) -- 동일한 것
```

키링 백엔드가 없으면 작업은 자동으로 파일 스토어로 폴백되고 일회성 경고가 출력되므로,
키링을 선택한 사용자가 자기 시크릿이 대신 파일에 있음을 알게 됩니다. 키링이 동작할 때는
키링이 권위(authoritative)를 가지며, 성공한 `set` / `unset`은 파일에 남은 낡은 평문 복사본도
지워서 키링을 선택한 뒤 파일 복사본이 남지 않게 합니다. 단 한 방향은 닫을 수 없습니다:
키링이 *다운된 동안* 파일에 기록된 값은 복구 시 키링으로 다시 이관되지 않으므로, 낡은
키링 값이 새 값을 가리는 일을 피하려면 키링이 닿는 동안 키를 교체하거나(또는 낡은 키링
항목을 지우고) 진행하세요.

## 로그에서 시크릿 가리기

```python
from xdgkit.scrub import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])                # __cause__/__context__ 체인 전체를 가림
```

`scrub_exception`은 절대 예외를 던지지 않으며 각 예외의 `args`와 문자열 `url` 속성을
다시 씁니다. 커스텀 `__str__`을 가진 예외라면 렌더된 로그 줄도 `scrub_secrets`에 함께
통과시키세요.

## 단일 인스턴스 잠금

```python
from xdgkit.locking import FileLock, single_instance

with single_instance("myapp", "poll") as acquired:
    if not acquired:
        return   # 다른 실행이 잠금을 쥐고 있음; 몰리지 말고 건너뜀
    ...

lock = FileLock("myapp", "poll")   # 또는 명시적으로 보유
if lock.acquire():
    try:
        ...
    finally:
        lock.release()
```

잠금은 `runtime_dir`에 위치하며 프로세스가 종료될 때 — 크래시가 나더라도 — OS가
해제합니다.

## 공개 API 레퍼런스

| Import | 무엇인가 |
|--------|----------|
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` (`xdgkit`) | 앱의 XDG 디렉터리 (`Path`). |
| `runtime_dir(app, *, create=True)` (`xdgkit`) | 보안된 세션 런타임 디렉터리. |
| `Credentials(app, *, shared=(), backend=None)` (`xdgkit`) | 4계층 시크릿 해석기: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `secret` / `require` / `set_secret` / `unset_secret` / `secret_names` (`xdgkit`) | `Credentials` 위의 모듈 수준 원샷 편의 함수. |
| `SecretBackend` / `FileBackend` / `KeyringBackend` / `default_backend` (`xdgkit.backends`) | 저장 seam과 두 구현. |
| `scrub_secrets` / `scrub_exception` (`xdgkit.scrub`) | 텍스트와 예외 체인에서 시크릿 값을 가림. |
| `FileLock` / `single_instance` (`xdgkit.locking`) | `runtime_dir`의 단일 인스턴스 advisory 잠금. |
| `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` (`xdgkit.permissions`) | 디렉터리/파일 권한 보장과 점검. |
| `write_bytes_atomic` / `write_text_atomic` (`xdgkit.atomic`) | 원자적 0600 쓰기. |
| `env_value` / `absolute_override` (`xdgkit.environment`) | 환경값 읽기(빈 값 = 없음) / 절대경로 override. |
| `app_dir_segment` (`xdgkit.paths`) | 앱 이름을 안전한 경로 세그먼트로 검증. |
| `XdgkitError` / `CredentialsError` / `InsecureStorageError` / `InvalidAppNameError` (`xdgkit`) | 예외 계층. |

## 라이브러리 작성자를 위해

xdgkit은 기반 계층만 제공합니다 — 디렉터리, 시크릿 해석, 권한, 원자적 쓰기, 잠금,
스크러빙. 당신의 패키지는 자기 도메인 설정(계정, 라우트, 토픽)을 그대로 유지하면서 그
아래에서 xdgkit을 가져다 씁니다:

```python
from xdgkit import config_dir, Credentials

def credentials_path():
    return config_dir("yourapp") / "credentials.json"

def api_key() -> str:
    return Credentials("yourapp").require("YOURAPP_API_KEY")
```

## 라이선스

MIT
