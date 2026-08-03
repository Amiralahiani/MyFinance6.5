import { expect } from "@playwright/test";
import { test } from "./visual-fixtures.js";

// This is a guided tour as well as a regression suite.  Keep the final state
// visible before moving to the next step in the same Chromium window.
test.afterEach(async ({ visualPage: page }) => {
  await page.waitForTimeout(3_000);
});

test("01 · ouvre l’espace Analyse et ses éléments essentiels", async ({ visualPage: page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Des réponses nettes/ })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Votre question" })).toBeVisible();
  await expect(page.getByText("RAPPORTS OFFICIELS 25", { exact: true })).toBeVisible();
});

test("02 · navigue de l’Analyse vers le registre des Sources", async ({ visualPage: page }) => {
  await page.getByRole("button", { name: /Sources/ }).click();
  await expect(page.locator("#analysis")).toHaveClass(/view-sources/);
  await expect(page.getByRole("heading", { name: /Chaque réponse peut être auditée/ })).toBeVisible();
});

test("03 · ouvre l’univers Portefeuilles", async ({ visualPage: page }) => {
  await page.getByRole("button", { name: /Portefeuilles/ }).click();
  await expect(page.locator("#analysis")).toHaveClass(/view-universe/);
  await expect(page.getByRole("heading", { name: /Les banques dans le radar/ })).toBeVisible();
});

test("04 · présente les cinq banques couvertes", async ({ visualPage: page }) => {
  await expect(page.locator(".bank-grid article")).toHaveCount(5);
  await expect(page.locator(".bank-grid")).toContainText("BIAT");
  await expect(page.locator(".bank-grid")).toContainText("Banque Zitouna");
});

test("05 · revient à l’Analyse sans perdre le navigateur", async ({ visualPage: page }) => {
  await page.getByRole("button", { name: /Analyse/ }).click();
  await expect(page.locator("#analysis")).toHaveClass(/view-analysis/);
  await expect(page.getByRole("textbox", { name: "Votre question" })).toBeVisible();
});

test("06 · répond à une valeur financière validée", async ({ visualPage: page }) => {
  await page.getByRole("textbox").fill("Quel est le PNB de BIAT en 2025 ?");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.locator(".value strong")).toHaveText("1 594 799");
  await expect(page.getByText(/Produit Net Bancaire/)).toBeVisible();
});

test("07 · ouvre la preuve PDF officielle de la valeur", async ({ visualPage: page }) => {
  await page.evaluate(() => {
    window.__openedDocumentUrl = null;
    window.open = (url) => {
      window.__openedDocumentUrl = url;
      return {};
    };
  });
  await page.getByRole("button", { name: /voir la source/i }).click();
  await expect.poll(() => page.evaluate(() => window.__openedDocumentUrl)).toMatch(
    /\/documents\/biat\/biat_efd311225\.pdf/
  );
});

test("08 · conserve le contexte de la métrique dans la même conversation", async ({ visualPage: page }) => {
  await page.getByRole("textbox").fill("et en 2024 ?");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.locator(".value strong").last()).toHaveText("1 479 714");
});

test("09 · complète un dossier documentaire après la banque et l’année", async ({ visualPage: page }) => {
  // One deliberate fresh session separates the metric journey from the new documentary dossier.
  await page.goto("/");
  await page.getByRole("textbox").fill("C'est quoi le portefeuille d'encaissement ?");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.getByText(/indiquez la banque et l’année/i)).toBeVisible();
  await page.getByRole("textbox").fill("BIAT 2021");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.locator(".document-answer")).toContainText("compte de tiers", { timeout: 15_000 });
  await expect(page.locator(".document-reference")).toContainText("p. 36");
});

test("10 · explique les conventions liées avec un périmètre prudent", async ({ visualPage: page }) => {
  await page.getByRole("textbox").fill("Transactions avec les parties liées de BIAT en 2021");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.locator(".document-reference").last()).toContainText("p. 38");
  await page.getByRole("textbox").fill("Et les autres ?");
  await page.getByRole("button", { name: /envoyer/i }).click();
  await expect(page.locator(".document-answer").last()).toContainText("d’autres conventions ou opérations examinées");
  await expect(page.locator(".document-answer").last()).not.toContainText("Au-delà du cas GSM");
  await page.getByText(/Voir les passages du rapport/).last().click();
  await expect(page.getByText(/Rapport officiel · page 117/)).toBeVisible();
});
