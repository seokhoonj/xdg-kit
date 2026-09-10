# credbox

[![check](https://github.com/seokhoonj/credbox/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/credbox/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/credbox)](https://pypi.org/project/credbox/)
[![Python](https://img.shields.io/pypi/pyversions/credbox)](https://pypi.org/project/credbox/)
[![License](https://img.shields.io/pypi/l/credbox)](https://github.com/seokhoonj/credbox/blob/main/LICENSE)

[English](README.md) | **한국어**

Python 앱·CLI용 시크릿 저장소. 경로는 기본 XDG, 요청 시 OS 네이티브(Linux/macOS/Windows). 시크릿은
로그·예외·트레이스백으로 새지 않도록 설계했습니다.

- **누출 방지** — 시크릿은 `Secret`으로 반환, 자동 마스킹, 실제 값은 `.reveal()`로만. 손상·실패·오류에도
  예외·트레이스백에 값 없음.
- **정직한 기본값** — 0700 디렉터리 안 0600 평문 `credentials.json`. 키링·암호화는 opt-in.
- **의존성 0** — `keyring`·`cryptography`는 필요 시 extra.

원자적 쓰기·권한·프로세스 간 잠금·XDG 경로·로그 마스킹을 한데 묶어 테스트했습니다. 디렉터리는
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/)을 따릅니다.

## 1. 설치

```sh
pip install credbox              # 파일 저장소, 의존성 0
pip install "credbox[keyring]"   # OS 키링 백엔드
pip install "credbox[crypto]"    # 암호화 파일 백엔드 (Argon2id + AES-GCM)
pip install "credbox[all]"       # keyring + crypto 모두
```

설치 확인은 `credbox --version`. Python 3.11 이상.

## 2. 빠른 시작

시크릿을 한 번 저장합니다(입력값은 화면에 표시되지 않습니다):

```sh
credbox set myapp API_KEY
```

코드에서 다시 읽습니다. `require`는 값을 찾고(`$API_KEY` → `myapp` 저장소 순), 없으면 예외를 냅니다.
반환값은 `Secret`이라 실수로 로그에 남지 않습니다:

```python
from credbox import Credentials

secret = Credentials("myapp").require("API_KEY")   # str이 아니라 Secret
secret.reveal()                                     # 실제 값 — 쓰는 자리에서만
print(secret)                                       # 'API_...cdef' — 마스킹되어 로그에 안전
```

## 3. 시크릿

시크릿(비밀번호·토큰·API 키)은 앱마다 하나인 `credentials.json`에 담깁니다 — 예: `myapp` →
`~/.config/myapp/credentials.json`. 이 파일이 앱의 **저장소(store)** 입니다. 읽을 저장소는 앱 이름으로
정해지므로, 한 앱이 다른 앱의 저장소를 이름으로 지목해 함께 읽을 수도 있습니다(아래 **공유 저장소**).

```python
from credbox import Credentials, Secret

# 해석 순서: override > 환경변수 > 공유 저장소 > 이 앱의 저장소
creds = Credentials("myapp", shared=["auth"])
key   = creds.require("API_KEY")          # $API_KEY, 그다음 auth 저장소, 그다음 myapp; 없으면 예외
maybe = creds.secret("API_KEY")           # 같지만 없으면 예외 대신 None
creds.set("API_KEY", value="sk-...")      # myapp 저장소에 저장 (str 또는 Secret; 키워드 전용)
creds.unset("API_KEY")                    # myapp 저장소에서 제거 (없으면 무시)
creds.names()                             # ["API_KEY", ...] — 이름만, 값은 아님

key.reveal()          # -> "sk-..."  HTTP 클라이언트에 넘길 실제 문자열
```

`secret`·`require`는 `Secret`을 반환합니다. 실제 문자열은 `.reveal()`로 꺼냅니다. `Secret`은 `str`·`repr`
에서 마스킹되고, 비교는 상수 시간이며, 해시할 수 없어 로그 한 줄이나 dict 키에 실수로 끼지 않습니다.
`set`은 `str`·`Secret`을 받고, 빈 값을 거부하며, 앞뒤 공백을 떼어 저장값과 조회값이 어긋나지 않게 합니다.

**공유 저장소**는 여러 앱이 함께 쓰는 키를 한 번만 두는 방법입니다 — 공유 앱(예: `"auth"`)에 저장하고, 각
앱이 `shared=["auth"]`로 함께 읽습니다. 한 앱에만 필요한 키는 그 앱 저장소에 둡니다.

## 4. `credbox` 명령

어느 앱의 시크릿이든 한 곳에서 같은 방식으로 다룹니다:

```sh
credbox set myapp API_KEY               # 화면에 표시하지 않고 입력받아 저장 (0600)
credbox set myapp API_KEY --value sk-…  # 값 직접 전달 (argv에 노출; 프롬프트 권장)
credbox list myapp                      # 이름만
credbox get myapp API_KEY               # 마스킹 출력 (API_…cdef); 저장값만
credbox get myapp API_KEY --reveal      # 전체 출력 (실제 값이 화면에 나가는 유일한 경로)
credbox get myapp API_KEY --resolve     # 환경변수까지 함께 참조
credbox unset myapp API_KEY
credbox path myapp                      # credentials.json 경로
credbox dirs myapp                      # 디렉터리 다섯 개
credbox doctor                          # 모든 앱의 권한 점검
```

`set`·`get`·`list`·`unset`에 `--keyring`을 붙이면 OS 키링 백엔드(파일 자동 폴백)를 씁니다. CLI는
트레이스백을 찍지 않고, 오류는 stderr에 값 없는 한 줄로 냅니다. 종료 코드는 성공 `0`, 명령 실패 `1`,
사용법 오류 `2`.

## 5. 백엔드

시크릿이 실제로 어디 저장되는지는 `SecretBackend`가 정합니다. `Credentials`는 기본 `FileBackend`를 쓰고,
`backend=`로 교체합니다:

```python
from credbox import Credentials, Secret
from credbox import default_backend, file_backend, keyring_backend, encrypted_backend

Credentials("myapp")                                                    # 파일 저장소 (기본)
Credentials("myapp", backend=default_backend(use_keyring=True))         # 파일 위에 키링
Credentials("myapp", backend=keyring_backend(fallback=file_backend()))  # 같은 것, 명시적으로
Credentials("myapp", backend=encrypted_backend(passphrase=Secret("…"))) # 암호화 파일 [crypto]
```

- **파일 저장소** (기본, 의존성 0) — 앱 폴더의 `credentials.json`. 어디서나 동작, 0600 평문 저장.
- **OS 키링** (`[keyring]`) — OS 볼트(macOS Keychain, GNOME Keyring 등). 쓸 수 있으면 키링이 우선이고,
  `set`·`unset` 성공 시 폴백 파일의 예전 평문 사본도 지웁니다. 키링이 **아예 없으면**(서버·cron·컨테이너)
  파일 저장소로 넘어가며 경고를 한 번 냅니다 — 사용자 모르게 평문으로 바꾸지 않습니다. **있는데 실패하면**
  (잠김·일시 오류) 평문을 쓰거나 예전 값을 주는 대신 예외를 냅니다(fail-closed). 파일 폴백은 키링이 아예
  없을 때만 씁니다. (정리는 *키링 → 파일* 한 방향뿐 — 키링을 못 쓰는 동안 파일에 쓴 값은 키링 복구 후
  자동으로 옮겨지지 않으니, 그때 키를 다시 `set` 하세요.)
- **암호화 파일** (`[crypto]`) — passphrase의 Argon2id 해시로 키를 만든 단일 AES-GCM 블롭. 폴백 없음: 암호
  오류·변조는 값 없는 `DecryptionError`로 실패하며 평문으로 물러서지 않습니다. 헤더 전체 인증(AAD), 쓸
  때마다 새 nonce, 의도적으로 무거운 KDF가 저장소를 열 때마다 ~100ms를 더합니다 — 버그가 아닙니다.

팩토리가 선택 import를 걸러 줍니다: extra가 없으면 `keyring_backend()`·`encrypted_backend()`는
`MissingExtraError`와 `pip install credbox[…]` 안내를 냅니다.

## 6. git 자격증명 헬퍼

credbox는 git에 자격증명을 넘길 수 있습니다. 헬퍼를 git에 지정합니다:

```sh
git config --global credential.helper credbox
```

git이 `get`·`store`·`erase`마다 `git-credential-credbox`를 부르고, git `host`를 credbox 앱 이름에,
`username`을 시크릿 이름에 대응시킵니다. `get`에서 헬퍼는 자격증명 응답만 stdout에 쓰고, 오류가 나면
아무것도 쓰지 않아(git이 직접 묻습니다) stderr에 값 없는 짧은 안내만 냅니다 — 시크릿도 트레이스백도
없습니다.

## 7. 디렉터리

```python
from credbox import config_dir, data_dir, state_dir, cache_dir, runtime_dir

config_dir("myapp")   # ~/.config/myapp        (또는 $XDG_CONFIG_HOME/...)
data_dir("myapp")     # ~/.local/share/myapp   (또는 $XDG_DATA_HOME/...)
state_dir("myapp")    # ~/.local/state/myapp   (또는 $XDG_STATE_HOME/...)
cache_dir("myapp")    # ~/.cache/myapp         (또는 $XDG_CACHE_HOME/...)
runtime_dir("myapp")  # $XDG_RUNTIME_DIR/myapp, 없으면 소유자만 접근하는 0700 임시 디렉터리
```

앱 이름은 경로 세그먼트 하나로 검증되어, 조작한 이름으로 기준 디렉터리를 벗어날 수 없습니다.
`data_dir`·`state_dir`은 앱별 `<PREFIX>_DATA_DIR`·`<PREFIX>_STATE_DIR` 오버라이드(지정한 절대경로를 그대로
사용)를 따르며, `<PREFIX>`는 `env_var_prefix(app)`가 만듭니다. 기본은 모든 OS에서 XDG `~/.config`이고,
`layout="native"`를 주면 OS 네이티브(Linux `~/.config`, macOS `~/Library/Application Support`, Windows
`%LOCALAPPDATA%`)를 쓰거나 `CREDBOX_LAYOUT`으로 지정합니다.

**Windows 참고:** 0600·0700 모드 비트는 POSIX 전용입니다. Windows엔 없어 credbox는 사용자별
`%LOCALAPPDATA%` ACL에 기대며, 지킬 수 없는 모드를 보장하지 않습니다.

## 8. 로그에서 시크릿 마스킹

API가 오류 메시지나 요청 URL에 키를 되비추는 일이 잦아, 손보지 않은 예외를 그대로 로깅하면 실패의 원인이
된 시크릿이 샐 수 있습니다. 아래 헬퍼는 알려진 시크릿 값과 그 URL 인코딩 형태를 로깅 전에 `***`로
바꿉니다:

```python
from credbox import scrub_secrets, scrub_exception

scrub_secrets("failed with sk-abc123", [key])   # "failed with ***"
raise scrub_exception(err, [key])               # __cause__·__context__ 사슬 전체 마스킹
```

`scrub_exception`은 예외를 내지 않으며, 각 예외의 `args`와 전송 URL(`url`·`request.url`·`response.url`),
PEP 678 `__notes__`를 다시 씁니다. `__str__`을 따로 정의한 예외라면 만들어진 로그 줄도 `scrub_secrets`에
한 번 통과시키세요.

## 9. 중복 실행 방지 (단일 인스턴스 잠금)

같은 작업이 두 번 겹쳐 도는 것을 막습니다 — cron 두 개, 또는 cron과 수동 실행. 이런 중복은 같은 일을 다시
하고, 결과를 두 번 내보내고, 공유 상태에서 경합합니다:

```python
from credbox import single_instance, FileLock

with single_instance("myapp", "poll") as acquired:
    if not acquired:
        return   # 다른 실행이 잠금을 쥠 — 건너뜁니다
    ...
```

잠금 파일은 `runtime_dir`에 있고, 크래시로 죽어도 종료 시 OS가 풉니다.

## 10. 공개 API 레퍼런스

### 자주 쓰는 API

| Import | 설명 |
|--------|------|
| `Credentials(app, *, shared=(), backend=None)` | 네 단계 시크릿 리졸버: `.secret` / `.require` / `.set` / `.unset` / `.names`. |
| `Secret` / `mask_secret` | 로그에 새지 않는 값 타입(`.reveal()`로 실제 문자열)과 표준 마스크. |
| `config_dir` / `data_dir` / `state_dir` / `cache_dir` / `runtime_dir` | 앱의 XDG 디렉터리. |
| `default_backend` / `file_backend` / `keyring_backend` / `encrypted_backend` | 백엔드 선택기와 팩토리. |
| `SecretBackend` / `FileBackend` | 백엔드 프로토콜과 의존성 0 파일 백엔드. |
| `scrub_secrets` / `scrub_exception` | 텍스트·예외 사슬에서 시크릿 값 마스킹. |
| `single_instance` / `FileLock` | `runtime_dir`의 단일 인스턴스 잠금. |
| `CredBoxError` / `CredentialsError` / `NoKeyringError` / `InsecureStorageError` / `InvalidAppNameError` / `DecryptionError` / `MissingExtraError` | 예외 계층. |
| `__version__` | 설치된 패키지 버전 문자열. |

### 빌딩 블록 (라이브러리 작성자용)

| Import | 설명 |
|--------|------|
| `ensure_dir` / `ensure_private_dir` / `restrict_dir_to_owner` / `warn_if_group_or_world_readable` | 디렉터리·파일 권한 보장과 점검. |
| `write_bytes_atomic` / `write_text_atomic` | 원자적 0600 쓰기. |
| `read_json` / `relocate_once` | 손상에 안전한 비-시크릿 상태 읽기; 여러 번 호출해도 안전한 재배치. |
| `env_var_prefix` / `colliding_env_var_prefixes` / `read_absolute_path_override` | 앱 이름을 환경변수 접두어로 변환·충돌 검사; 절대경로 오버라이드 읽기. |
| `app_dir_segment` / `Layout` / `default_layout` / `set_default_layout` | 앱 이름 검증; 경로 레이아웃 선택. |

## 11. 라이브러리 작성자를 위해

credbox는 바닥 계층만 제공합니다 — 디렉터리·시크릿 해석·권한·원자적 쓰기·잠금·마스킹. 작성자의 패키지는
자기 도메인 설정(계정·라우트·토픽)은 그대로 두고, 그 아래에서 저장 위치와 시크릿만 credbox에 맡깁니다:

```python
from credbox import Credentials, config_dir

settings = config_dir("myapp") / "settings.toml"     # 설정 파일은 직접 관리
token    = Credentials("myapp").secret("API_TOKEN")  # 저장 위치와 시크릿만 credbox에
```

## 12. 라이선스

MIT
