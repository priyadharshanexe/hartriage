import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { UploadPage } from "./UploadPage";

describe("UploadPage", () => {
  it("explains what happens to the file before anything is uploaded", async () => {
    mockApi({ "POST /v1/auth/refresh": SESSION });
    renderApp(<UploadPage />);
    expect(await screen.findByRole("heading", { name: "Analyse a HAR file" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing is sent to any AI service/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeEnabled();
  });

  it("does not let viewers upload", async () => {
    mockApi({ "POST /v1/auth/refresh": { ...SESSION, role: "viewer" } });
    renderApp(<UploadPage />);
    expect(await screen.findByText(/Viewers can read analyses/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeDisabled();
  });
});
