import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Executa o módulo real de identidade visual (sem navegador).
const source = readFileSync(new URL('../src/identidade.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports });
const { luminancia, contraste, paletaDaIdentidade, paletaDaEmpresa } = exports;

test('luminância: preto 0, branco 1 e valor inválido 0', () => {
  assert.equal(luminancia('#000000'), 0);
  assert.ok(Math.abs(luminancia('#FFFFFF') - 1) < 1e-9);
  assert.equal(luminancia('azul'), 0);
});

test('contraste entre preto e branco é 21', () => {
  assert.ok(Math.abs(contraste('#000000', '#ffffff') - 21) < 1e-6);
});

test('fundo escuro usa texto claro e botão ativo claro', () => {
  const p = paletaDaIdentidade('#241a12', '#4a2410');
  assert.equal(p.textoClaro, true);
  assert.equal(p.vars['--sb-fg'], '#F3E9DD');
  assert.equal(p.vars['--sb-ativo-fg'], '#241A12');
  assert.match(p.fundo, /linear-gradient\(160deg, #241a12 0%, #4a2410 100%\)/);
});

test('fundo claro usa texto escuro', () => {
  const p = paletaDaIdentidade('#fff4d6', '#ffe0a3');
  assert.equal(p.textoClaro, false);
  assert.equal(p.vars['--sb-fg'], '#241A12');
  assert.equal(p.vars['--sb-ativo-bg'], '#241A12');
});

test('gradiente com uma ponta clara e outra escura escolhe o texto de melhor pior-caso', () => {
  const p = paletaDaIdentidade('#ffffff', '#000000');
  // Nenhum dos dois textos é perfeito nas duas pontas; vale o que tem o melhor contraste mínimo.
  const minClaro = Math.min(contraste('#F3E9DD', '#ffffff'), contraste('#F3E9DD', '#000000'));
  const minEscuro = Math.min(contraste('#241A12', '#ffffff'), contraste('#241A12', '#000000'));
  assert.equal(p.textoClaro, minClaro >= minEscuro);
});

test('sem as duas cores a empresa usa o visual padrão', () => {
  assert.equal(paletaDaEmpresa(null), null);
  assert.equal(paletaDaEmpresa({ nome: 'X', logo_url: null, cor_principal: '#112233', cor_contraste: null }), null);
  assert.ok(paletaDaEmpresa({ nome: '', logo_url: null, cor_principal: '#112233', cor_contraste: '#445566' }));
});
