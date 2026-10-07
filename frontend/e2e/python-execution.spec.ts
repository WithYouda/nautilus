import {expect,test} from '@playwright/test';
import {authorize} from './fact-helpers';

test('manual Python: edit, output, charts, cancel, reload and mobile',async({page})=>{
 test.setTimeout(90000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await authorize(page);
 expect((await page.request.put('/api/ai/provider',{data:{display_name:'Synthetic Python',base_url:process.env.NAUTILUS_E2E_MOCK_PROVIDER_URL,model:'mock-python',api_key:'synthetic',enabled:true,request_timeout_seconds:15}})).ok()).toBeTruthy();
 await page.reload();await page.getByRole('button',{name:'学习室',exact:true}).click();await page.getByRole('button',{name:'新建对话',exact:true}).click();
 const input=page.getByLabel('输入学习问题',{exact:true});await input.fill('合成 Python 代码测试');await input.press('Enter');
 const open=page.getByRole('button',{name:'运行代码',exact:true});await expect(open).toBeVisible({timeout:15000});await open.click();
 const dialog=page.getByRole('dialog',{name:'运行 Python 代码',exact:true});
 await expect(dialog.getByRole('button',{name:'启用并运行',exact:true})).toBeEnabled();
 await dialog.getByRole('button',{name:'启用并运行',exact:true}).click();
 await expect(dialog.getByLabel('Python输出',{exact:true})).toContainText('6',{timeout:20000});
 await expect(dialog.getByAltText('运行生成的图表 1')).toBeVisible();
 await dialog.screenshot({path:'/tmp/nautilus-python-desktop.png'});
 await dialog.getByLabel('代码',{exact:true}).fill("print('EDITED-RESULT')");await dialog.getByRole('button',{name:'运行',exact:true}).click();
 await expect(dialog.getByLabel('Python输出',{exact:true})).toContainText('EDITED-RESULT',{timeout:15000});
 await dialog.getByLabel('代码',{exact:true}).fill('import time\ntime.sleep(20)');await dialog.getByRole('button',{name:'运行',exact:true}).click();
 await expect(dialog.getByRole('button',{name:'取消运行',exact:true})).toBeVisible();await dialog.getByRole('button',{name:'取消运行',exact:true}).click();
 await expect(dialog.locator('.python-output-head strong')).toHaveText('已取消');
 await dialog.getByRole('button',{name:'关闭代码运行'}).click();await page.reload();await page.getByRole('button',{name:'运行代码',exact:true}).click();
 await expect(dialog.getByLabel('选择代码运行记录').locator('option')).toHaveCount(3);
 await dialog.getByLabel('选择代码运行记录').selectOption({index:0});await expect(dialog.getByAltText('运行生成的图表 1')).toBeVisible();
 await page.setViewportSize({width:390,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await dialog.screenshot({path:'/tmp/nautilus-python-390.png'});
 expect(errors).toEqual([]);
});
