[English](README.md) | **한국어**

# xdg-kit

파이썬을 위한 안전한 XDG 스타일 애플리케이션 저장소: 경로, 자격증명, 권한, 런타임 파일.

모든 커맨드라인 앱이 디스크에서 해야 하는 두 가지 — **파일이 어디 있는지 찾기**와
**시크릿(비밀값)을 해석하기** — 를 모든 OS에서 똑같은 방식으로 한 번에 처리하는, 작고
의존성 없는 기반입니다.

- **디렉터리**는 [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)
  (`config` / `data` / `state` / `cache` / `runtime`)를 따르며, 모든 플랫폼에서 `~/.config`
  레이아웃을 사용합니다 — git이 이미 따르는 것과 같은 관례라 머신마다 경로가 동일하고
  별도의 플랫폼 라이브러리가 필요 없습니다.
- **시크릿**은 정해진 순서로 해석됩니다 — 명시적 값, 그다음 환경변수, 그다음 공유
  저장소, 마지막으로 앱 자신의 저장소 — 그래서 여러 앱이 공통으로 쓰는 키를 각 앱에
  복사하지 않고 **한 곳**에 둘 수 있습니다.
- **저장**은 기본적으로 0700 디렉터리 안의 mode 0600 `credentials.json` 평문 파일입니다
  (헤드리스 환경과 여러 머신에서 신뢰할 수 있음). OS 키링(keyring)은 파일 자동 폴백이
  딸린 opt-in 백엔드입니다.

## 1. 설치

```sh
pip install xdg-kit            # 파일 저장소, 런타임 의존성 0
pip install "xdg-kit[keyring]" # OS 키링(keyring) 사용 시 설치하는 옵션
```

설치 확인:

```sh
xdg-kit --version
```

Python 3.11+ 필요.

## 2. 디렉터리

```python
from xdg_kit import config_dir, data_dir, state_dir, cache_dir, runtime_dir

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

## 3. 시크릿

시크릿(비밀번호, 토큰, API 키)은 **앱 이름별 `credentials.json` 파일 하나**에 담깁니다 --
`config_dir(app)/credentials.json`, 예를 들어 `myapp` 앱이면 `~/.config/myapp/credentials.json`.
이 파일 하나가 그 앱의 **저장소**입니다. 어떤 저장소를 읽을지는 앱 이름으로 정해지므로, 한
앱이 자기 저장소뿐 아니라 다른 앱의 저장소도 이름으로 지정해 함께 읽을 수 있습니다(아래
**공유 저장소**).

```python
from xdg_kit import Credentials, secret, require, set_secret, unset_secret, secret_names

# 해석 순서: override > 환경변수 > 공유 저장소 > 이 앱의 저장소
creds = Credentials("myapp", shared=["auth"])
key = creds.require("API_KEY")         # $API_KEY, 그다음 auth 저장소, 그다음 myapp 저장소; 없으면 예외
maybe = creds.secret("API_KEY")        # 같은 해석, 단 없으면 예외 대신 None 반환
creds.set("API_KEY", value="sk-...")   # myapp 자신의 저장소에 기록 (value는 키워드 전용)
creds.unset("API_KEY")                 # myapp 저장소에서 삭제 (없으면 무시)
creds.names()                          # ["API_KEY", ...] -- 이름만, 값은 절대 반환하지 않음

# 모듈 수준 원샷 편의 함수 (각각 내부에서 Credentials를 구성):
secret("myapp", "API_KEY")                       # -> str | None
require("myapp", "API_KEY")                      # -> str, 없으면 CredentialsError
set_secret("myapp", "API_KEY", value="sk-...")   # value는 키워드 전용
unset_secret("myapp", "API_KEY")                 # 이 앱의 저장소에서 삭제 (없으면 무시)
secret_names("myapp")                            # -> list[str]
```

**공유 저장소**는 여러 앱이 공통으로 쓰는 키의 중복을 없애는 방법입니다. 공유 앱(예:
`"auth"`) 하나에 한 번 저장하면, 모든 소비자가 `shared=["auth"]`로 그 키를 해석합니다. 한
앱에만 특정한 키는 그 앱 자신의 저장소에 남습니다.

## 4. `xdg-kit` 명령

각 패키지마다 다른 키 저장 방식을 익힐 필요 없이, 어떤 앱의 시크릿이든 한 곳에서 한
형식으로 관리합니다:

```sh
xdg-kit set myapp API_KEY               # 에코 없이 입력받아 credentials.json(0600)에 기록
xdg-kit set myapp API_KEY --value sk-…  # 직접 전달도 가능(argv에 노출되니 입력 프롬프트 권장)
xdg-kit list myapp                      # 이름만, 값은 절대 안 보임
xdg-kit get myapp API_KEY               # 마스킹(sk***ef); 저장된 값만 읽음
xdg-kit get myapp API_KEY --reveal      # 전체 출력
xdg-kit get myapp API_KEY --resolve     # 저장된 값뿐 아니라 환경변수도 함께 참조
xdg-kit unset myapp API_KEY
xdg-kit path myapp                      # credentials.json 경로 출력
xdg-kit dirs myapp                      # 다섯 디렉터리 모두 출력
xdg-kit doctor                          # 모든 앱의 자격증명 파일/디렉터리 권한 점검
xdg-kit doctor myapp other-app          # 지정한 앱만 점검
```

`set`, `get`, `list`, `unset`은 `--keyring`을 받아 OS 키링 백엔드로 동작합니다(파일 자동
폴백 포함). 종료 코드: `0` 성공, `1` 런타임 오류, `2` 사용법 오류(잘못된 앱 이름).

## 5. 키링

비밀번호나 API 키 같은 시크릿은 두 곳 중 하나에 저장할 수 있습니다:

- **파일 저장소**(기본) — 앱 폴더의 `credentials.json`. 어디서나 확실히 동작하지만, 값이
  평문(그대로 보이는 형태)으로 들어갑니다.
- **OS 키링**(옵션) — OS가 제공하는 암호화 금고(맥 Keychain, 리눅스 GNOME Keyring 등). 더
  안전하지만, 화면 없는 서버 · cron 예약 실행 · 컨테이너처럼 키링이 없거나 잠긴 곳에서는
  쓸 수 없습니다.

기본을 파일로 둔 건 "어디서나 된다"는 신뢰성 때문입니다. 키링을 쓰려면 직접 켜야 합니다:

```python
from xdg_kit.backends import FileBackend, KeyringBackend, default_backend
from xdg_kit import Credentials

backend = KeyringBackend(fallback=FileBackend())   # 키링을 쓰되, 안 될 때는 파일로
creds = Credentials("myapp", backend=backend)
# 또는: default_backend(use_keyring=True) -- 같은 뜻
```

이렇게 켜면 xdg-kit은 이렇게 동작합니다.

- **평소(키링이 열려 있을 때)**: 값은 키링에 저장되고, 그 값에 대한 권한을 키링이 가집니다
  — 파일에도 같은 키가 있으면 키링 값이 이깁니다. `set` / `unset`이 성공하면 파일에 남아
  있던 예전 평문 복사본까지 지워서, 키링으로 옮긴 뒤 파일에 사본이 남지 않게 합니다.
- **키링을 쓸 수 없을 때(설치 안 됨 · 잠김 · 서버라 키링이 없음)**: 작업이 자동으로 파일
  저장소로 물러납니다(폴백 -- 대비책으로 내려감). 이때 경고가 한 번 떠서, 키링을 켠
  사용자가 "지금 값이 키링이 아니라 파일에 저장됐다"는 걸 알 수 있습니다.

**주의할 점 하나** -- 반대 방향은 자동으로 정리되지 않습니다. 키링을 쓸 수 없던 동안 파일에
저장된 값은, 나중에 키링이 다시 열려도 키링으로 자동으로 옮겨지지 않습니다. 그래서 키링에
예전 값이 그대로 남아 있으면, 읽을 때 키링을 먼저 보기 때문에 그 예전 값이 새 값을
가려버립니다. 확실한 해결은 **키링이 열려 있을 때 키를 다시 설정(set)하는 것**입니다 -- 그러면
새 값이 곧장 키링으로 들어가고 파일에 남은 낡은 사본도 지워집니다. `xdg-kit unset --keyring`으로
예전 키링 항목을 지워서 고치려 하지 *마세요*: 키링이 열려 있는 동안에는 그 명령이 파일에 있던
새 사본까지 함께 지워 값을 잃습니다.

## 6. 로그에서 시크릿 가리기

API는 종종 에러 메시지나 요청 URL 안에 당신의 키를 그대로 되돌려줍니다. 그래서 안 가린
예외를 그냥 로그에 남기면, 실패에 쓰인 바로 그 시크릿이 로그 파일이나 터미널로 새어 나갈 수
있습니다. 이 함수들은 로그로 내보내기 전에 알려진 시크릿 값을 `***`로 바꿉니다.

```python
from xdg_kit.scrub import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # __cause__/__context__ 체인 전체를 가림
```

`scrub_exception`은 절대 예외를 던지지 않으며 각 예외의 `args`와 문자열 `url` 속성을
다시 씁니다. 커스텀 `__str__`을 가진 예외라면 렌더된 로그 줄도 `scrub_secrets`에 함께
통과시키세요.

## 7. 단일 인스턴스 잠금

같은 작업이 자기 자신의 다른 복사본과 겹쳐 도는 것을 막습니다 — cron 두 개, 또는 cron과
수동 실행이 겹칠 때. 그러면 같은 일을 두 번 하고, 같은 출력이 중복으로 나가고(중복 전송,
중복 레코드), 공유 상태에서 경쟁(race)이 생깁니다(두 실행이 한 파일을 동시에 써서 깨뜨림).
`FileLock`은 나중 실행이 "이미 하나가 돌고 있음"을 감지해, 몰리지 않고 건너뛰게 해줍니다.

```python
from xdg_kit.locking import FileLock, single_instance

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

## 8. 공개 API 레퍼런스

| Import | 무엇인가 |
|--------|----------|
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` (`xdg_kit`) | 앱의 XDG 디렉터리 (`Path`). |
| `runtime_dir(app, *, create=True)` (`xdg_kit`) | 보안된 세션 런타임 디렉터리. |
| `Credentials(app, *, shared=(), backend=None)` (`xdg_kit`) | 4계층 시크릿 해석기: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `secret` / `require` / `set_secret` / `unset_secret` / `secret_names` (`xdg_kit`) | `Credentials` 위의 모듈 수준 원샷 편의 함수. |
| `SecretBackend` / `FileBackend` / `KeyringBackend` / `default_backend` (`xdg_kit.backends`) | 저장 seam과 두 구현. |
| `scrub_secrets` / `scrub_exception` (`xdg_kit.scrub`) | 텍스트와 예외 체인에서 시크릿 값을 가림. |
| `FileLock` / `single_instance` (`xdg_kit.locking`) | `runtime_dir`의 단일 인스턴스 advisory 잠금. |
| `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` (`xdg_kit.permissions`) | 디렉터리/파일 권한 보장과 점검. |
| `write_bytes_atomic` / `write_text_atomic` (`xdg_kit.atomic`) | 원자적 0600 쓰기. |
| `env_value` / `absolute_override` (`xdg_kit.environment`) | 환경값 읽기(빈 값 = 없음) / 절대경로 override. |
| `app_dir_segment` (`xdg_kit.paths`) | 앱 이름을 안전한 경로 세그먼트로 검증. |
| `XdgKitError` / `CredentialsError` / `InsecureStorageError` / `InvalidAppNameError` (`xdg_kit`) | 예외 계층. |

## 9. 라이브러리 작성자를 위해

xdg-kit은 기반 계층만 제공합니다 — 디렉터리, 시크릿 해석, 권한, 원자적 쓰기, 잠금,
스크러빙. 당신의 패키지는 자기 도메인 설정(계정, 라우트, 토픽)을 그대로 유지하면서 그
아래에서 xdg-kit을 가져다 씁니다:

```python
from xdg_kit import config_dir, Credentials

def credentials_path():
    return config_dir("yourapp") / "credentials.json"

def api_key() -> str:
    return Credentials("yourapp").require("YOURAPP_API_KEY")
```

## 10. 라이선스

MIT
