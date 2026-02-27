class Tidydownloads < Formula
  include Language::Python::Virtualenv

  desc "Local AI-powered download organizer using Ollama"
  homepage "https://github.com/federico-reppucci/tidydownloads"
  url "https://github.com/federico-reppucci/tidydownloads/archive/refs/tags/v0.1.0.tar.gz"
  sha256 ""  # TODO: fill after `git tag v0.1.0 && git push --tags`
  license "MIT"

  depends_on "python@3.12"
  depends_on "poppler"
  depends_on "ollama"

  resource "flask" do
    url "https://files.pythonhosted.org/packages/41/e1/d104c83026f8d35dfd2c261df7d64738f4b5a1a2076c27a36f13c2f5e047/flask-3.1.0.tar.gz"
    sha256 "5f1c7c5a2b3cd0f1f144d790c0a1f57713de1e65fa08a1cdab7987007ba03948"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      First-time setup:

        1. Start Ollama:   brew services start ollama
        2. Run first scan: tidydownloads scan

      The first scan will automatically download the default AI model (~3.3 GB).

      For faster scans, set before starting Ollama:
        export OLLAMA_NUM_PARALLEL=4
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/tidydownloads --help")
  end
end
