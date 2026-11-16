"""Local browser acceptance flow. Requires a fresh disposable standalone DB and QA login."""
import argparse
import os
from pathlib import Path
from playwright.sync_api import sync_playwright


def run(url,username,password,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        launch={'headless':True}
        if os.environ.get('NEXUS_BROWSER_EXECUTABLE'):launch['executable_path']=os.environ['NEXUS_BROWSER_EXECUTABLE']
        browser=pw.chromium.launch(**launch)
        page=browser.new_page(viewport={'width':1440,'height':900})
        errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/blueprint')
        page.locator('#username').fill(username);page.locator('#password').fill(password)
        page.get_by_role('button',name='Войти',exact=True).click()
        page.locator('#workspace').wait_for(state='visible')
        page.locator('#upload').set_input_files(str(Path(__file__).resolve().parents[1]/'examples/blueprint/sea-coop.json'))
        page.get_by_role('button',name='Проверить и импортировать',exact=True).click()
        page.get_by_role('button',name='Утвердить версию',exact=True).click()
        page.locator('#projectName').get_by_text('Морской кооператив',exact=True).wait_for()
        page.get_by_role('button',name='Что делать сейчас',exact=True).click()
        page.locator('#now .task').first.get_by_role('button',name='Открыть').click()
        page.get_by_role('textbox',name='Результат проверки').fill('Проверены GDD, ограничения и исходный промпт. Неизвестная зона — эксклюзивный режим до подтверждения.')
        page.get_by_role('button',name='Подтвердить промпт и зоны',exact=True).click()
        page.get_by_role('button',name='Скопировать промпт для ChatGPT / Claude',exact=True).click()
        page.wait_for_function("() => document.querySelector('textarea[aria-label=\"Полный промпт для исполнителя\"]').value.includes('Исходный промпт')")
        assert 'эксклюзивный' in page.get_by_role('textbox',name='Полный промпт для исполнителя').input_value()
        page.locator('#taskBody .badge').get_by_text('В работе',exact=True).wait_for()
        page.get_by_role('combobox',name='Новый статус').select_option('tests_passed')
        page.get_by_role('button',name='Сохранить статус',exact=True).click()
        page.locator('#taskBody .badge').get_by_text('Тесты пройдены',exact=True).wait_for()
        page.get_by_role('textbox',name='Решение и результаты').fill('Критерии проверены, результат принимаю.')
        page.get_by_role('combobox',name='Новый статус').select_option('accepted')
        page.get_by_role('button',name='Сохранить статус',exact=True).click()
        page.locator('#taskBody .badge').get_by_text('Принята',exact=True).wait_for()
        page.get_by_role('button',name='Закрыть карточку',exact=True).click()
        for width,height,label in [(360,800,'mobile'),(1440,900,'desktop')]:
            page.set_viewport_size({'width':width,'height':height})
            for theme in ['light','dark']:
                page.evaluate('(theme)=>{document.body.classList.toggle("dark",theme==="dark");localStorage.setItem("bp_theme",theme)}',theme)
                for name,tab in [('blueprint','Blueprint проекта'),('roadmap','Дорожная карта'),('now','Что делать сейчас'),('versions','Версии Blueprint')]:
                    page.get_by_role('button',name=tab,exact=True).click()
                    page.screenshot(path=str(output/f'{label}-{theme}-{name}.png'),full_page=True)
                    assert page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'),f'Overflow {label} {theme} {name}'
                page.get_by_role('button',name='Дорожная карта',exact=True).click()
                page.locator('#roadmap .task').nth(1).get_by_role('button',name='Открыть').click()
                page.screenshot(path=str(output/f'{label}-{theme}-task.png'),full_page=True)
                assert page.evaluate('() => document.querySelector("dialog").scrollWidth <= document.querySelector("dialog").clientWidth'),f'Dialog overflow {label} {theme}'
                page.get_by_role('button',name='Закрыть карточку',exact=True).click()
        # Import an unapproved revision containing hostile text; preview must render inert text.
        import json
        payload=json.loads((Path(__file__).resolve().parents[1]/'examples/blueprint/sea-coop.json').read_text())
        payload['tasks'][0]['prompt']='<img src=x onerror="window.xssExecuted=true">'
        page.get_by_role('button',name='Blueprint проекта',exact=True).click()
        page.locator('#upload').set_input_files({'name':'hostile.json','mimeType':'application/json','buffer':json.dumps(payload).encode()})
        page.get_by_role('button',name='Проверить и импортировать',exact=True).click()
        page.locator('#preview').get_by_text('Версия 2 · Морской кооператив',exact=True).wait_for()
        page.locator('#preview summary').click()
        assert not page.evaluate('() => Boolean(window.xssExecuted)')
        assert page.locator('#preview img').count()==0
        assert not errors,errors
        browser.close()
        print('PASS: login → import → preview → approve → review → copy → dispatch → tests → accept; 20 screenshots; no overflow or JS errors')

if __name__=='__main__':
    import getpass
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765');p.add_argument('--username',default='owner');p.add_argument('--output',default='docs/qa/blueprint');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if not a.self_test:
        run(a.url,a.username,getpass.getpass('Local QA password: '),a.output)
    else:
        import sys,secrets,tempfile,threading,time
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        import uvicorn
        from backend.blueprint.app import create_app,password_hash
        with tempfile.TemporaryDirectory() as tmp:
            password=secrets.token_urlsafe(24)
            app=create_app(Path(tmp)/'test.sqlite',{'owner':{'hash':password_hash(password),'role':'owner'}},False)
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8765,log_level='warning'))
            thread=threading.Thread(target=server.run,daemon=True);thread.start()
            for _ in range(200):
                if server.started:break
                time.sleep(.05)
            try:run('http://127.0.0.1:8765','owner',password,a.output)
            finally:server.should_exit=True;thread.join(timeout=10)
