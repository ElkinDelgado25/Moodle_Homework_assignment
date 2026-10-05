import 'dotenv/config';
import { chromium } from 'playwright';

const config = {
  baseUrl: requiredEnv('MOODLE_URL').replace(/\/+$/, ''),
  username: requiredEnv('MOODLE_USERNAME'),
  password: requiredEnv('MOODLE_PASSWORD'),
  headless: process.env.MOODLE_HEADLESS !== 'false',
};

function requiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Falta la variable ${name}. Cópiala desde .env.example a .env.`);
  }
  return value;
}

function absoluteUrl(href) {
  return new URL(href, `${config.baseUrl}/`).href;
}

function cleanText(value) {
  return (value ?? '').replace(/\s+/g, ' ').trim();
}

function firstText(locator) {
  return locator.first().textContent().then(cleanText).catch(() => '');
}

async function login(page) {
  await page.goto(`${config.baseUrl}/login/index.php`, { waitUntil: 'domcontentloaded' });

  const loginForm = page.locator('form#login, form[action*="login"]');
  if (await loginForm.count() === 0) {
    return;
  }

  await page.locator('input[name="username"]').fill(config.username);
  await page.locator('input[name="password"]').fill(config.password);
  await page.locator('button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState('domcontentloaded');

  if (page.url().includes('/login/')) {
    const message = await firstText(page.locator('[data-region="messages"], .alert-danger, .loginerrors'));
    throw new Error(`Moodle no aceptó el inicio de sesión${message ? `: ${message}` : '.'}`);
  }
}

async function findAssignmentLinks(page) {
  const pagesToScan = [`${config.baseUrl}/my/`, `${config.baseUrl}/my/courses.php`];
  const links = new Set();

  for (const url of pagesToScan) {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    const hrefs = await page.locator('a[href*="/mod/assign/view.php"]').evaluateAll((anchors) =>
      anchors.map((anchor) => anchor.href),
    );
    hrefs.forEach((href) => links.add(href));
  }

  return [...links];
}

async function readAssignment(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });

  const title = cleanText(await page.locator('h1, .page-header-headings h1').first().textContent());
  const content = await firstText(page.locator(
    '.activity-description, .mod_introbox, .box.generalbox, [data-region="activity-information"]',
  ));
  const dueDate = await firstText(page.locator(
    '[data-region="activity-information"] .description, .activity-dates, .assign-dates',
  ));
  const status = await firstText(page.locator(
    '[data-region="submissions"], .submissionstatus, .submissionstatustable',
  ));
  const isSubmitted = /submitted|entregad|enviado|calificad/i.test(status);

  return {
    title: title || 'Tarea sin título',
    url: page.url(),
    content: content || 'No se encontró una descripción visible.',
    dueDate: dueDate || 'Fecha de vencimiento no indicada.',
    status: status || 'Estado de entrega no visible.',
    isSubmitted,
  };
}

function printTasks(tasks) {
  const pending = tasks.filter((task) => !task.isSubmitted);
  const now = new Date();
  const stamp = now.toLocaleString('es-EC', {
    dateStyle: 'full',
    timeStyle: 'short',
  });

  console.log(`\nConsulta de Moodle: ${stamp}`);
  console.log(`Tareas revisadas: ${tasks.length}`);

  if (pending.length === 0) {
    console.log('\n✅ No se encontraron tareas pendientes de entrega.');
    return;
  }

  console.log(`\n⚠️ Tienes ${pending.length} tarea(s) pendiente(s):\n`);
  pending.forEach((task, index) => {
    console.log(`${index + 1}. ${task.title}`);
    console.log(`   Vence: ${task.dueDate}`);
    console.log(`   Estado: ${task.status}`);
    console.log(`   Contenido: ${task.content}`);
    console.log(`   Enlace: ${task.url}\n`);
  });
}

async function main() {
  const browser = await chromium.launch({ headless: config.headless });
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);

  try {
    await login(page);
    const assignmentLinks = await findAssignmentLinks(page);
    const tasks = [];

    for (const url of assignmentLinks) {
      try {
        tasks.push(await readAssignment(page, url));
      } catch (error) {
        console.warn(`No se pudo leer ${url}: ${error.message}`);
      }
    }

    printTasks(tasks);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`\n❌ No fue posible consultar Moodle: ${error.message}`);
  process.exitCode = 1;
});
