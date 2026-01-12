import java.util.Scanner;

public class Main {

    /**
     * 辅助函数：根据字符和重复次数构建字符串
     * @param c 要重复的字符
     * @param count 重复次数
     * @return 构造好的字符串
     */
    private static String repeat(char c, int count) {
        if (count <= 0) {
            return "";
        }
        StringBuilder sb = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            sb.append(c);
        }
        return sb.toString();
    }

    public static void main(String[] args) {
        Scanner scanner = new Scanner(System.in);
        int n = scanner.nextInt();

        // 1. 构造并打印上部（竖条）
        // 规律: n个'*' + 2n个'.' + n个'*'
        String verticalRow = repeat('*', n) + repeat('.', 2 * n) + repeat('*', n);

        for (int i = 0; i < 3 * n; i++) {
            System.out.println(verticalRow);
        }

        // 2. 构造并打印下部（底座）
        // 循环 n 次，k 从 1 到 n
        for (int k = 1; k <= n; k++) {
            String baseRow;
            String leadingDots = repeat('.', k);

            if (k == n) {
                // 这是最后一行 (k=n)
                // 规律: n个'.' + 2n个'*' + n个'.'
                baseRow = leadingDots + repeat('*', 2 * n) + leadingDots;
            } else {
                // 这不是最后一行 (k < n)
                // 规律: k个'.' + n个'*' + 2*(n-k)个'.' + n个'*' + k个'.'
                String stars = repeat('*', n);
                String middleDots = repeat('.', 2 * (n - k));
                baseRow = leadingDots + stars + middleDots + stars + leadingDots;
            }

            System.out.println(baseRow);
        }

        scanner.close();
    }
}