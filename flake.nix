{
  description = "Python CUDA + uv development shell";

  inputs = { nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05"; };

  outputs = { self, nixpkgs }:
    let
      pkgs = import nixpkgs {
        system = "x86_64-linux";
        config.allowUnfree = true;
        cudaSupport = true;
      };
    in {
      # 定义一个可供 'nix develop' 使用的 shell
      devShells.x86_64-linux.default = pkgs.mkShell {
        packages = with pkgs; [ uv cudaPackages.cudatoolkit cacert zsh ];
        # 在进入 shell 时自动设置环境
        shellHook = ''
          echo "--- NixOS CUDA + uv Shell ---"
          echo "CUDA Toolkit 11 is available."
          echo "Using Hugging Face mirror: hf-mirror.com"

          # Hugging Face mirror
          export HF_ENDPOINT="https://hf-mirror.com"

          # 某些包可能需要这个来找到 CUDA
          export LD_LIBRARY_PATH="${pkgs.cudaPackages.cudatoolkit}/lib:$LD_LIBRARY_PATH"
          export CUDA_PATH=${pkgs.cudaPackages.cudatoolkit}
          export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          exec zsh
        '';
      };
    };
}
