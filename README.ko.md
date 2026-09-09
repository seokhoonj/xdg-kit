# credbox

[![check](https://github.com/seokhoonj/credbox/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/credbox/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/credbox)](https://pypi.org/project/credbox/)
[![Python](https://img.shields.io/pypi/pyversions/credbox)](https://pypi.org/project/credbox/)
[![License](https://img.shields.io/pypi/l/credbox)](https://github.com/seokhoonj/credbox/blob/main/LICENSE)

[English](README.md) | **한국어**

Python 앱과 CLI를 위한, 설계상 누출-안전(leak-safe, 시크릿이 로그·예외·트레이스백으로 새지 않도록
구조적으로 보장)한 **XDG 위치의 시크릿 저장소**.

명령줄 앱은 시크릿을 해석하고 파일 위치를 찾아야 합니다. credbox는 이 둘을 모든 OS에서 한 방식으로
처리하며, **시크릿을 흘리지 않는 것**을 본연의 임무로 삼습니다.

- **누출-안전.** 해석된 시크릿은 로그나 트레이스백에서 스스로 마스킹되는 `Secret`으로 돌아오고, raw
  값은 사용하는 지점에서 `.reveal()`로만 꺼냅니다. 저장소가 손상됐거나, OS 키링이 실패했거나, 암호화
  passphrase가 틀려도 **내용 없는(content-free)** 에러만 납니다 — 값은 예외에도, 그 `__cause__`/
  `__context__` 체인에도, 트레이스백에도 실리지 않습니다. CLI와 git 헬퍼는 오직 명시적 reveal에서만
  raw 시크릿을 stdout에 씁니다.
- **기본이 정직함.** 저장은 0700 디렉터리 안의 0600 `credentials.json` 평문 — 헤드리스와 여러 머신에서
  안정적입니다. OS 키링과 암호화 파일 백엔드는 **옵트인** 업그레이드이며, 키링 부재는 명시적으로 경고된
  폴백일 뿐 조용한 다운그레이드가 아닙니다.
- **의존성 0 코어.** 기본 파일 저장소는 아무것도 끌어오지 않습니다. `keyring`과 `cryptography`는 요청할
  때만 설치되고, 코어의 import 그래프는 절대 이들에 닿지 않습니다.

credbox는 `keyring` 생태계의 아이디어를 안전하게 재포장한 것입니다 — 원자적 쓰기, 올바른 권한, 교차
프로세스 잠금, XDG 경로, 누출 스크러빙을 한 단위로 묶어 테스트했습니다. 디렉터리는
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)을 따릅니다.

## 1. 설치

```sh
pip install credbox              # 파일 저장소, 런타임 의존성 0
pip install "credbox[keyring]"   # OS 키링 백엔드 추가
pip install "credbox[crypt]"     # 암호화 파일 백엔드 추가 (Argon2id + AES-GCM)
pip install "credbox[all]"       # 둘 다
```

확인:

```sh
credbox --version
```

Python 3.11+ 필요.

## 2. 빠른 시작

시크릿을 한 번 저장(입력 에코 없음):

```sh
credbox set myapp API_KEY
```

코드에서 다시 읽습니다. `require`는 값을 해석하고(`$API_KEY`, 없으면 `myapp` 저장소) 어디에도 없으면
예외를 냅니다. 결과는 `Secret`이라 실수로 로그에 남지 않습니다:

```python
from credbox import Credentials

secret = Credentials("myapp").require("API_KEY")   # str이 아니라 Secret
secret.reveal()                                     # raw 값, 사용하는 지점에서만
print(secret)                                       # 'API_...cdef' — 마스킹됨, 로그에 안전
```

## 3. 시크릿

시크릿(비밀번호, 토큰, API 키)은 **앱마다 하나의 `credentials.json`**에 삽니다 —
`config_dir(app)/credentials.json` (예: `myapp` -> `~/.config/myapp/credentials.json`). 이 파일이
앱의 **저장소(store)** 입니다. 어느 저장소를 읽을지는 앱 이름으로 정해지므로, 한 앱이 다른 앱의
저장소를 이름으로 지목해 자기 것과 함께 읽을 수 있습니다(아래 **공유 저장소** 참고).

```python
from credbox import Credentials, Secret

# 해석 순서: override > 환경변수 > 공유 저장소들 > 이 앱의 저장소
creds = Credentials("myapp", shared=["auth"])
key   = creds.require("API_KEY")          # env $API_KEY, 그다음 auth 저장소, 그다음 myapp; 없으면 예외
maybe = creds.secret("API_KEY")           # 같지만 예외 대신 None
creds.set("API_KEY", value="sk-...")      # myapp 자기 저장소에 씀 (str 또는 Secret; 키워드 전용)
creds.unset("API_KEY")                    # myapp 저장소에서 제거 (없으면 no-op)
creds.names()                             # ["API_KEY", ...] — 이름만, 값은 절대 아님

key.reveal()          # -> "sk-..."  HTTP 클라이언트에 넘길 raw 문자열
```

`secret`과 `require`는 `Secret`을 반환합니다. raw 문자열은 `.reveal()`로 꺼내세요. `Secret`은
`str`/`repr`에서 마스킹되고, 상수 시간 비교를 하며, unhashable이라 로그 줄이나 dict 키에 실수로 끼지
않습니다. `set`은 `str`이나 `Secret`을 받고, 빈 값을 거부하며, 앞뒤 공백을 제거해 저장된 키가 해석
결과와 일치하도록 합니다.

**공유 저장소**는 여러 앱이 공통으로 쓰는 키의 중복을 없애는 방법입니다 — 공유 앱(예: `"auth"`)에 한 번
저장하고, 각 소비자가 `shared=["auth"]`로 해석합니다. 한 앱에만 특정한 키는 그 앱 저장소에 둡니다.

## 4. `credbox` 명령

어떤 앱의 시크릿이든 한 곳에서, 한 형식으로 관리:

```sh
credbox set myapp API_KEY               # 에코 없이 입력받아 credentials.json(0600)에 씀
credbox set myapp API_KEY --value sk-…  # 직접 전달 (argv에 노출됨; 프롬프트 권장)
credbox list myapp                      # 이름만, 값은 절대 아님
credbox get myapp API_KEY               # 마스킹됨 (API_…cdef); 저장된 값만 읽음
credbox get myapp API_KEY --reveal      # 전체 출력 (raw 시크릿이 stdout으로 나가는 유일한 경로)
credbox get myapp API_KEY --resolve     # 환경변수까지 함께 참조
credbox unset myapp API_KEY
credbox path myapp                      # credentials.json 경로 출력
credbox dirs myapp                      # 5개 디렉터리 출력
credbox doctor                          # 모든 앱의 credentials 파일/디렉터리 권한 점검
```

`set`·`get`·`list`·`unset`은 `--keyring`으로 OS 키링 백엔드(자동 파일 폴백)를 씁니다. CLI는 트레이스백을
절대 출력하지 않습니다 — 런타임 에러는 stderr에 내용 없는 한 줄로 나옵니다. 종료코드: `0` 성공, `1`
명령 실패, `2` 사용법 오류.

## 5. 백엔드

시크릿이 물리적으로 어디 저장되는지는 `SecretBackend`입니다. `Credentials`는 기본으로 `FileBackend`를
쓰고, `backend=`로 다른 것을 고릅니다:

```python
from credbox import Credentials, Secret
from credbox import default_backend, file_backend, keyring_backend, encrypted_backend

Credentials("myapp")                                                    # 파일 저장소 (기본)
Credentials("myapp", backend=default_backend(use_keyring=True))         # 파일 위에 키링
Credentials("myapp", backend=keyring_backend(fallback=file_backend()))  # 같은 것, 명시적
Credentials("myapp", backend=encrypted_backend(passphrase=Secret("…"))) # 암호화 파일 [crypt]
```

- **파일 저장소** (기본, 의존성 0) — 앱 폴더의 `credentials.json`. 어디서나 안정적이며, 값을 0600 평문으로
  저장합니다.
- **OS 키링** (`[keyring]`) — OS 제공 볼트(macOS Keychain, GNOME Keyring 등). 닿을 수 있으면 그것이 권한을
  가지며, 성공한 `set`/`unset`은 폴백 파일의 오래된 평문 사본도 지웁니다. **부재**할 때(서버·cron·컨테이너에
  백엔드 없음)는 모든 작업이 파일 저장소로 폴백하며 내용 없는 일회성 경고를 냅니다 — 키링을 켠 사용자가
  값이 파일로 갔음을 알게 되고, 조용한 다운그레이드는 없습니다. **있지만 실패**하는 키링(예: 잠김)은
  `get`/`set`은 폴백하되 `unset`은 fail-closed로 예외를 냅니다(삭제 안 됐을 수 있는데 삭제됐다고 보고하지
  않음). (한 가지 주의: 조정은 키링 -> 파일 한 방향만입니다. 키링이 죽은 동안 파일에 쓴 값은 되돌려 옮겨지지
  않으니, 키링이 닿을 때 키를 다시 `set` 하세요.)
- **암호화 파일** (`[crypt]`) — passphrase의 Argon2id 해시로 키를 만든 단일 AES-GCM blob. **terminal**입니다:
  틀린 passphrase나 변조된 파일은 내용 없는 `DecryptionError`로 fail-closed하며, 평문 다운그레이드는 없습니다.
  헤더 전체가 인증되고(AES-GCM AAD), 쓰기마다 새 nonce를 뽑으며, 의도적으로 비싼 KDF가 저장소 열 때마다
  ~100ms대 지연을 더합니다 — 버그가 아니라 기능입니다.

팩토리는 옵셔널 import를 게이트합니다: `keyring_backend()`/`encrypted_backend()`는 해당 extra가 설치되지
않았으면 `MissingExtraError`(그리고 `pip install credbox[…]` 힌트)를 냅니다.

## 6. git 자격증명 헬퍼

credbox는 git에 자격증명을 제공할 수 있습니다. 설치된 헬퍼를 git에 지정하세요:

```sh
git config --global credential.helper credbox
```

그러면 git이 `get`/`store`/`erase`마다 `git-credential-credbox`를 호출하며, git `host`를 credbox 앱에,
git `username`을 시크릿 이름에 매핑합니다. `get`에서 헬퍼는 자격증명 응답만 stdout에 쓰고, 에러 시에는
아무것도 쓰지 않고(그러면 git이 프롬프트) 내용 없는 메모만 stderr에 냅니다 — 시크릿도 트레이스백도 아닙니다.

## 7. 디렉터리

```python
from credbox import config_dir, data_dir, state_dir, cache_dir, runtime_dir

config_dir("myapp")   # ~/.config/myapp        (또는 $XDG_CONFIG_HOME/...)
data_dir("myapp")     # ~/.local/share/myapp   (또는 $XDG_DATA_HOME/...)
state_dir("myapp")    # ~/.local/state/myapp   (또는 $XDG_STATE_HOME/...)
cache_dir("myapp")    # ~/.cache/myapp         (또는 $XDG_CACHE_HOME/...)
runtime_dir("myapp")  # $XDG_RUNTIME_DIR/myapp, 없으면 보안된 0700 임시 디렉터리
```

앱 이름은 단일 경로 세그먼트로 검증되므로, 조작된 이름이 베이스를 벗어날 수 없습니다. `data_dir`과
`state_dir`은 앱별 `<PREFIX>_DATA_DIR`/`<PREFIX>_STATE_DIR` 오버라이드(그대로 쓰이는 절대경로)를 존중하며,
`<PREFIX>`는 `env_var_prefix(app)`입니다. 기본은 모든 OS에서 XDG `~/.config` 레이아웃이며,
`layout="native"`로 OS 네이티브 위치(macOS `~/Library/Application Support`, Windows `%LOCALAPPDATA%`)를
쓰거나 `CREDBOX_LAYOUT`을 설정할 수 있습니다.

**Windows 주의:** 0600/0700 모드 비트는 POSIX 전용입니다. Windows엔 그런 모드가 없어 credbox는 사용자별
`%LOCALAPPDATA%` ACL에 의존하며, 거기서 제공할 수 없는 모드 보장을 주장하지 않습니다.

## 8. 로그에서 시크릿 가리기

API가 에러 메시지나 요청 URL에 키를 되비추는 일이 잦아서, 스크럽 안 된 예외를 로깅하면 실패의 원인이 된 바로
그 시크릿이 샐 수 있습니다. 아래 헬퍼는 알려진 시크릿 값 — 그리고 그 URL-인코딩 형태 — 을 로깅 전에 `***`로
바꿉니다:

```python
from credbox import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # __cause__/__context__ 체인 전체를 스크럽
```

`scrub_exception`은 절대 예외를 내지 않으며, 각 예외의 `args`, 전송 URL(`url`·`request.url`·`response.url`),
PEP 678 `__notes__`를 다시 씁니다. 커스텀 `__str__`을 가진 예외라면 렌더된 로그 줄도 `scrub_secrets`에
통과시키세요.

## 9. 단일 인스턴스 잠금

같은 잡의 다른 사본과 겹치는 것을 막습니다 — cron 두 개, 혹은 cron과 수동 실행. 이런 중복은 작업을 다시 하고,
중복 산출을 내며, 공유 상태에서 경합합니다:

```python
from credbox import single_instance, FileLock

with single_instance("myapp", "poll") as acquired:
    if not acquired:
        return   # 다른 실행이 잠금을 쥠; 밀어붙이지 말고 건너뜀
    ...
```

잠금은 `runtime_dir`에 있으며, 크래시가 나도 프로세스 종료 시 OS가 해제합니다.

## 10. 공개 API 레퍼런스

### 일상 API (`credbox`)

| Import | 무엇인가 |
|--------|------------|
| `Credentials(app, *, shared=(), backend=None)` | 4-tier 시크릿 리졸버: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `Secret` / `mask_secret` | 누출-안전 값 타입(`.reveal()`로 raw 문자열)과 그 표준 마스크. |
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` / `runtime_dir` | 앱의 XDG 디렉터리. |
| `default_backend` / `file_backend` / `keyring_backend` / `encrypted_backend` | 백엔드 선택기와 팩토리. |
| `SecretBackend` / `FileBackend` | 백엔드 프로토콜과 의존성 0 파일 백엔드. |
| `scrub_secrets` / `scrub_exception` | 텍스트·예외 체인에서 시크릿 값 가리기. |
| `single_instance` / `FileLock` | `runtime_dir`의 단일 인스턴스 어드바이저리 잠금. |
| `CredBoxError` / `CredentialsError` / `NoKeyringError` / `InsecureStorageError` / `InvalidAppNameError` / `DecryptionError` / `MissingExtraError` | 예외 계층. |
| `__version__` | 설치된 패키지 버전 문자열. |

### 빌딩 블록 (라이브러리 작성자용 — 직접 호출은 드묾)

| Import | 무엇인가 |
|--------|------------|
| `ensure_dir` / `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` | 디렉터리/파일 권한 보장과 점검. |
| `write_bytes_atomic` / `write_text_atomic` | 원자적 0600 쓰기. |
| `read_json` / `relocate_once` | 손상 인지 비-시크릿 상태 읽기; 멱등·fail-closed 재배치. |
| `env_var_prefix` / `colliding_env_var_prefixes` / `read_absolute_path_override` | 앱 이름 env 폴딩과 절대경로 오버라이드. |
| `app_dir_segment` / `Layout` / `default_layout` / `set_default_layout` | 앱 이름 검증; 경로 레이아웃 선택. |

## 11. 라이선스

MIT
