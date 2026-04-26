# Monix 제품 요구사항 정의서 (PRD)

## 1. 개요 (Overview)
**Monix**는 터미널 환경에서 서버 상태를 모니터링하고 제어할 수 있는 CLI 기반의 AI(Gemini/Claude) 어시스턴트입니다. 읽기 전용 모니터링 작업을 자연어 또는 슬래시(`/`) 명령어를 통해 쉽고 빠르게 수행할 수 있도록 돕습니다. 

본 문서는 Monix의 핵심 기능과 특히 서버 모니터링 시 필수적으로 지원해야 하는 주요 대상(Target)에 대한 요구사항을 정의합니다.

## 2. 목표 (Goals)
* 터미널 내에서 대화형 인터페이스를 통해 서버의 상태를 즉각적으로 파악
* 복잡한 명령어 없이 자연어로 서버 상태(CPU, 메모리, 로그 등) 조회
* LLM(Gemini 등)을 통한 상태 분석 및 위험 요소 사전 알림

## 3. 주요 기능 (Core Features)

### 3.1. 대화형 CLI 인터페이스 (Interactive CLI)
* 텍스트 기반의 대화형 프롬프트 제공 (REPL 환경)
* `/status`, `/watch`, `/top`, `/logs`, `/service` 등 단축 명령어 지원
* AI와의 질의응답을 통한 서버 진단 (`/ask`)

### 3.2. 모니터링 대상 (Monitoring Targets)
Monix는 다음의 주요 지표와 대상을 모니터링할 수 있어야 합니다.

#### 1) 시스템 리소스 모니터링
* **CPU**
  * 전체 CPU 사용률(%) 실시간 측정
  * 상위 CPU 점유 프로세스(`top`) 조회 기능
  * 임계치(`MONIX_CPU_WARN`, 기본 85%) 초과 시 경고 알림

* **Memory**
  * 전체 메모리 대비 사용/가용 메모리 용량 및 사용률(%) 조회
  * 임계치(`MONIX_MEM_WARN`, 기본 85%) 초과 시 경고 알림

* **Disk**
  * 주요 마운트 포인트(예: `/`)의 디스크 전체 크기 및 여유 공간, 사용률(%) 조회
  * 임계치(`MONIX_DISK_WARN`, 기본 90%) 초과 시 경고 알림

#### 2) 애플리케이션 및 시스템 로그 모니터링
* **Application Log**
  * 지정한 애플리케이션 로그 파일 실시간 조회 (Tail 기능)
  * 특정 라인 수만큼의 로그를 빠르게 가져오는 기능 (`/logs [path] [lines]`)

* **Nginx Log**
  * Nginx의 Access Log 및 Error Log 조회
  * 서비스 동작 상태와 웹 서버 에러 진단을 위한 로그 분석 지원

#### 3) 인프라 및 서비스 모니터링
* **컨테이너 모니터링 (Container Monitoring)** *[신규/추가 요구사항]*
  * Docker 등 컨테이너 런타임 환경에서 실행 중인 컨테이너 목록 및 상태 조회
  * 개별 컨테이너의 리소스 사용량(CPU, Memory) 및 컨테이너 로그 조회 기능 지원
  * 향후 `docker stats` 및 `docker logs` 등의 명령어를 래핑하여 연동 예정

* **Systemd 서비스 상태**
  * 특정 서비스(예: nginx, apache, mysql)의 활성화 및 실행 상태(status) 확인

## 4. 아키텍처 및 동작 방식 (Architecture & Workflow)
* **제한적/읽기 전용 (Read-only)**: 서버 설정 변경, 파일 수정, 프로세스 강제 종료 등은 수행하지 않으며, 오직 상태 조회와 로그 확인에만 집중합니다.
* **로컬 Fallback**: LLM API 키(예: `ANTHROPIC_API_KEY` 또는 `GEMINI_API_KEY`)가 없는 환경에서도 로컬 룰 기반으로 기본적인 명령어와 자연어 매칭이 작동해야 합니다.
* **크로스 플랫폼**: Linux(procfs 기반) 및 macOS(vm_stat 기반 등) 환경을 모두 지원해야 합니다.

## 5. 향후 과제 (Future Scope)
* 컨테이너 모니터링(Docker/Podman) 모듈(`monix/tools/containers.py` 등) 신규 개발 및 통합
* 컨테이너 전용 명령어(`/container` 등) 추가 및 자연어 컨텍스트 연동
* LLM을 통한 비정상 로그(에러 로그, 성능 저하 로그 등) 자동 탐지 및 요약 기능 강화
