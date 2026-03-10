class Tidyup < Formula
  include Language::Python::Virtualenv

  desc "Local AI-powered download organizer using Ollama"
  homepage "https://github.com/federico-reppucci/tidyup"
  url "https://github.com/federico-reppucci/tidyup/archive/refs/tags/v0.3.0.tar.gz"
  sha256 "2f001bf99cdffc7472e1fb50cebaa1694ed0ffcacfdf21b396f74c5c4a1a6e9b"
  license "MIT"
  head "https://github.com/federico-reppucci/tidyup.git", branch: "main"

  depends_on "python@3.12"
  depends_on "poppler"
  depends_on "ollama"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      First-time setup:

        1. Start Ollama:   brew services start ollama
        2. Run first scan: tidyup scan

      The first scan will automatically download the default AI model (~3.3 GB).

      For faster scans, set before starting Ollama:
        export OLLAMA_NUM_PARALLEL=4
    EOS
  end

  test do
    assert_match "usage", shell_output("#{bin}/tidyup --help")
  end
end
