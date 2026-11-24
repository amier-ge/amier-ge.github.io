# amier_ge 블로그

- `src/site/` — Hugo 레이아웃, 스타일, JavaScript, About·Contact 원문
- `src/editor/` — 브라우저 Markdown 편집기
- `src/server/` — Google 로그인 검증, 문서 게시, 방문자 집계
- `src/deploy/` — EC2 서비스와 Nginx 설정
- `assets/` — 프로필·파비콘, 글 이미지, 공개 파일
- `blog/` — 글 원문과 선택적인 영어 번역

## 로컬 미리보기

Hugo Extended 0.162.1을 설치한 뒤 저장소 루트에서 `hugo server -D`를 실행합니다.
파일이나 폴더를 옮겨도 기존 글의 숫자 `slug`를 유지합니다. 이전 글 경로는
`aliases`, 기존 Giscus 토론 키는 `commentTerm`에 보존됩니다.

## EC2 편집

[편집실](https://amier.ge/editor/)에서 승인된 Google 계정으로 로그인합니다.
한·영 글을 편집하고, 파일을 선택하거나 본문에 붙여넣어 첨부할 수 있습니다.
초안은 편집실에 저장되고, 게시할 때만 Hugo가 다시 빌드됩니다.

Google 웹 클라이언트는 승인된 JavaScript 원본에 `https://amier.ge`를 등록합니다.
EC2 서비스의 로그인 설정은 `/etc/amier-blog/editor.env`, 초안·게시물 수정·방문 통계·
첨부 파일은 `/var/lib/amier-blog/private/`에 저장합니다.
공개 사이트는 `/var/lib/amier-blog/public`에 연결된 빌드에서 제공됩니다.

GitHub Pages 빌드는 저장소에 있는 Markdown을 게시합니다. EC2의 편집실에서
저장한 내용은 Git 저장소에 자동으로 커밋되지 않습니다.

테스트는 저장소 루트에서 Python 의존성을 설치한 다음
`python -m unittest discover -s src/server -p test_blog.py`로 실행합니다.
