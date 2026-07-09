# 남는 맥북을 복지소식 서버로 만들기

Railway 없이, 남는 맥북 한 대로 운영하는 방법입니다. 맥북이 하는 일은 두 가지:

1. **대시보드 화면** 24시간 띄우기
2. **매일 오전 10시 30분, AI 초안 자동 생성** — Claude Code로 실행되므로
   Claude Max 요금제에 포함되어 **API 비용이 들지 않습니다**

정책 수집과 텔레그램 알림은 GitHub Actions(클라우드, 무료)가 하므로
맥북이 꺼져 있어도 수집은 계속되고, 글 생성만 다음 날로 밀립니다.

---

## 준비물

- 남는 맥북 1대 (전원 어댑터 연결 필수)
- 집 와이파이
- 폰 (밖에서 접속용)

---

## 1단계. 프로젝트 내려받기

맥북에서 **터미널** 앱을 열고 (Spotlight에서 "터미널" 검색), 한 줄씩 입력합니다:

```bash
cd ~
git clone https://github.com/사용자이름/bokjisosik.git
cd bokjisosik
```

> 처음 git을 쓰면 "command line developer tools" 설치 창이 뜰 수 있습니다. "설치"를 눌러주세요. 끝나면 위 명령을 다시 실행합니다.

## 2단계. 프로그램 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs
```

## 3단계. Claude Code 설치 + 로그인 (AI 글 생성용)

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

설치가 끝나면:

```bash
claude
```

처음 실행하면 로그인 안내가 나옵니다. **Claude Max 계정으로 로그인**하세요.
로그인 후 `/exit` 를 입력해 나옵니다. 이제 이 맥북에서 AI 글 생성은 Max 요금제로 처리됩니다.

## 4단계. 설정 파일(.env) 만들기

```bash
cp .env.example .env
open -e .env
```

텍스트 편집기가 열리면 각 항목을 채우고 저장합니다.
(GITHUB_TOKEN, GITHUB_REPO, WP 정보, 텔레그램, DASHBOARD_PASSWORD)

> **ANTHROPIC_API_KEY는 비워두세요.** 비워두면 자동으로 Claude Code(Max 포함)로 글을 생성합니다.

## 5단계. 서버 켜보기 (테스트)

```bash
chmod +x run_dashboard.sh run_generate.sh
./run_dashboard.sh
```

맥북의 인터넷 브라우저에서 `http://localhost:8000` 을 열어 로그인 화면이 나오면 성공입니다.
확인했으면 터미널에서 `control + C` 로 일단 끕니다.

AI 생성도 한 번 테스트해봅니다 (미작성 정책이 있으면 실제로 글이 만들어집니다):

```bash
./run_generate.sh
tail -30 logs/generate.log
```

## 6단계. 자동 실행 등록 (서버 + 매일 글 생성)

```bash
whoami
```

나오는 이름(예: `kimbokji`)을 기억해두고, 설정 파일 2개를 엽니다:

```bash
open -e setup/com.bokjisosik.dashboard.plist
open -e setup/com.bokjisosik.generate.plist
```

각 파일 안의 `여기에사용자이름`을 전부 방금 나온 이름으로 바꾸고 저장합니다. 그 다음:

```bash
cp setup/com.bokjisosik.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.bokjisosik.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.bokjisosik.generate.plist
```

이제:
- 맥북을 재시작해도 대시보드가 자동으로 켜지고, 죽어도 되살아납니다
- 매일 **오전 10시 30분**에 AI 초안이 자동 생성됩니다 (수집은 GitHub이 10시에 완료)

## 7단계. 맥북이 잠들지 않게 하기

1. 전원 어댑터를 항상 연결해둡니다.
2. **시스템 설정 → 배터리(또는 에너지 절약) → 전원 어댑터** 에서
   "디스플레이가 꺼져 있을 때 자동으로 잠자기 방지"를 **켭니다**.
3. 뚜껑은 **열어둔 채** 화면 밝기만 최저로 낮춰두는 게 가장 안전합니다.
   - 뚜껑을 닫고 쓰고 싶다면 터미널에서: `sudo pmset -a disablesleep 1`
     (되돌리기: `sudo pmset -a disablesleep 0`)

## 8단계. 밖에서 폰으로 접속하기 (Tailscale)

1. 맥북: https://tailscale.com 에서 앱을 내려받아 설치하고 구글 계정으로 로그인
2. 폰: 앱스토어에서 **Tailscale** 설치, 같은 계정으로 로그인
3. 폰의 Tailscale 앱에 맥북 이름이 보이면, 폰 브라우저에서:
   `http://맥북이름:8000` (예: `http://kims-macbook:8000`)

이러면 외부에 서버를 공개하지 않고도, 전 세계 어디서든 폰으로 대시보드에 접속됩니다.
집 와이파이에 있을 때는 Tailscale 없이 `http://맥북이름.local:8000` 으로도 접속됩니다.

---

## 자주 묻는 것

**맥북이 꺼지면 글 수집도 멈추나요?**
수집과 알림은 GitHub Actions(클라우드)가 하므로 계속 돌아갑니다.
멈추는 건 대시보드 화면과 그날의 AI 글 생성뿐이고, 다음 날 맥북이 켜져 있으면 밀린 것부터 생성합니다.

**AI 글 생성 비용은 정말 안 드나요?**
네. 맥북의 Claude Code는 사용 중인 Claude Max 요금제에 포함되어 실행됩니다.
다만 Max의 사용량 한도를 조금 나눠 쓰는 것이라, 하루 생성량(AUTO_GENERATE_LIMIT)을
과도하게 올리면 본인이 Claude를 쓸 때 한도에 더 빨리 닿을 수 있습니다.

**전기료는 얼마나 나오나요?**
맥북 대기 전력은 5~10W 수준으로, 한 달 내내 켜둬도 전기료 몇백 원 정도입니다.

**macOS 업데이트가 뜨면?**
업데이트 후 재시동되면 서버는 자동으로 다시 켜집니다(5단계 설정 덕분).
단, 재시동 후 로그인은 한 번 해줘야 할 수 있습니다.

**서버가 안 켜져 있는 것 같으면?**
터미널에서 `tail -20 ~/bokjisosik/logs/dashboard.log` 를 입력하면 서버 기록을 볼 수 있습니다.
